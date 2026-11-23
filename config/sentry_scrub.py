"""Repo-local Sentry scrubbing (sentry-sdk 3.x).

sentry-sdk 3.0 removed ``EventScrubber`` (and its ``DEFAULT_DENYLIST``), which
2.x ran on every event. This module re-applies the same denylist, plus the
2.x PII keys, everywhere the old scrubber looked (request headers, cookies,
data and env, ``extra``, ``user``, breadcrumb data, stack-frame variables),
and to span names and attributes for ``before_send_span``.

It only ever removes data: a key is sensitive when it is one of the 2.x
denylist keys, or when it *contains* one of a few fragments (``password``,
``token``, ``secret``…), which is stricter than 2.x. ``key=value`` pairs and
``Bearer`` credentials inside strings are masked too.

Self-contained on purpose: no SDK internals, so a future SDK release cannot
break it at import time. Nothing here may raise into the SDK — in 3.0 an
exception in a callback drops the event (or, for a span, restores the
unscrubbed original) — so both entry points fall back to stripping.
"""

from __future__ import annotations

import re
from typing import Any

FILTERED = "[Filtered]"

#: sentry-sdk 2.x ``DEFAULT_DENYLIST`` + ``DEFAULT_PII_DENYLIST``, normalised
#: (lower case, ``-`` -> ``_``) and matched on the whole key.
_EXACT_KEYS = frozenset(
    k.lower().replace("-", "_")
    for k in (
        "password", "passwd", "secret", "api_key", "apikey", "auth",
        "credentials", "mysql_pwd", "privatekey", "private_key", "token",
        "session", "csrftoken", "sessionid", "x_csrftoken", "set_cookie",
        "cookie", "authorization", "proxy-authorization", "x_api_key",
        "aiohttp_session", "connect.sid", "csrf_token", "csrf", "_csrf",
        "_csrf_token", "PHPSESSID", "_session", "symfony", "user_session",
        "_xsrf", "XSRF-TOKEN",
        # PII (send_default_pii=False)
        "x_forwarded_for", "x_real_ip", "ip_address", "remote_addr",
    )
)

#: A key containing any of these (after normalisation) is sensitive too.
_KEY_FRAGMENTS = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "cookie", "session", "csrf", "xsrf", "private_key",
    "privatekey", "credential", "jwt", "bearer", "totp", "otp_",
)

_SECRET_WORDS = (
    r"password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization|"
    r"session(?:id)?|csrf\w*|xsrf\w*|jwt|signature|code|otp"
)
#: ``name=value`` (query strings, form bodies, log lines) with a sensitive name.
_PAIR_RE = re.compile(
    r"(?i)(\b[\w.\-\[\]]*(?:" + _SECRET_WORDS + r")[\w.\-\[\]]*=)[^&\s#;,'\"]+"
)
#: ``Bearer <credential>`` / ``Basic <credential>``.
_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")

_MAX_DEPTH = 12

#: Event sections stripped when scrubbing itself fails (never leak on error).
_RISKY_SECTIONS = ("request", "extra", "user", "breadcrumbs")


def is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    norm = key.lower().replace("-", "_")
    if norm in _EXACT_KEYS or norm.rsplit(".", 1)[-1] in _EXACT_KEYS:
        return True
    return any(fragment in norm for fragment in _KEY_FRAGMENTS)


def scrub_text(text: str) -> str:
    """Mask sensitive ``name=value`` pairs and ``Bearer`` credentials."""
    text = _PAIR_RE.sub(lambda m: m.group(1) + FILTERED, text)
    return _SCHEME_RE.sub(lambda m: m.group(1) + " " + FILTERED, text)


def scrub_data(value: Any, depth: int = 0) -> Any:
    """Scrub dicts / lists in place (sensitive keys, sensitive pairs in
    strings) and return the scrubbed value."""
    if isinstance(value, str):
        return scrub_text(value)
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = FILTERED if is_sensitive_key(key) else scrub_data(item, depth + 1)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = scrub_data(item, depth + 1)
        return value
    return value


def _iter_frames(event: dict[str, Any]):
    stacktraces = []
    for section in ("exception", "threads"):
        container = event.get(section)
        if isinstance(container, dict):
            for item in container.get("values") or ():
                if isinstance(item, dict):
                    stacktraces.append(item.get("stacktrace"))
    stacktraces.append(event.get("stacktrace"))
    for stacktrace in stacktraces:
        if isinstance(stacktrace, dict):
            for frame in stacktrace.get("frames") or ():
                if isinstance(frame, dict):
                    yield frame


def _scrub_event(event: dict[str, Any]) -> None:
    request = event.get("request")
    if isinstance(request, dict):
        for key in ("headers", "cookies", "data", "env"):
            if key in request:
                request[key] = scrub_data(request[key])
        for key in ("url", "query_string"):
            if isinstance(request.get(key), str):
                request[key] = scrub_text(request[key])
    if "extra" in event:
        event["extra"] = scrub_data(event["extra"])
    user = event.get("user")
    if isinstance(user, dict):
        user.pop("ip_address", None)
        scrub_data(user)
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        for crumb in breadcrumbs.get("values") or ():
            if isinstance(crumb, dict) and "data" in crumb:
                crumb["data"] = scrub_data(crumb["data"])
    for frame in _iter_frames(event):
        if "vars" in frame:
            frame["vars"] = scrub_data(frame["vars"])


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scrub an error event in place and return it. Never raises: on an
    unexpected shape it strips the risky sections and frame variables."""
    try:
        _scrub_event(event)
    except Exception:
        for key in _RISKY_SECTIONS:
            event.pop(key, None)
        try:
            for frame in _iter_frames(event):
                frame.pop("vars", None)
        except Exception:
            event.pop("exception", None)
            event.pop("threads", None)
            event.pop("stacktrace", None)
    return event


def scrub_span(span: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """``before_send_span``: scrub the span name and attributes. A span
    cannot be dropped here (3.0); use ``ignore_spans`` for that. Never
    raises: on failure the name is masked and the attributes emptied, since
    the SDK would otherwise send the unscrubbed original."""
    try:
        name = span.get("name")
        if isinstance(name, str):
            span["name"] = scrub_text(name)
        attributes = span.get("attributes")
        if isinstance(attributes, dict):
            for key, value in attributes.items():
                if is_sensitive_key(key):
                    attributes[key] = FILTERED
                elif isinstance(value, str):
                    attributes[key] = scrub_text(value)
                elif isinstance(value, list):
                    attributes[key] = [
                        scrub_text(v) if isinstance(v, str) else v for v in value
                    ]
    except Exception:
        span["name"] = FILTERED
        span["attributes"] = {}
    return span
