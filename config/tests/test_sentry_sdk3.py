"""sentry-sdk 3.x configuration, exercised through a real client.

``sentry_options`` is what production passes to ``sentry_sdk.init``; a capture
transport collects the envelopes instead of sending them.
"""

import logging
import warnings

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from config.sentry import before_send, sentry_options
from config.sentry_scrub import FILTERED, scrub_event, scrub_span

_OPTIONS = {"dsn": "https://public@o0.ingest.sentry.io/1", "environment": "test", "release": "test"}


class _CaptureTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)

    def items(self, kind):
        return [
            item.payload.json
            for envelope in self.envelopes
            for item in envelope.items
            if item.type == kind
        ]


@pytest.fixture
def sentry(request):
    traces_sample_rate = getattr(request, "param", 0.0)
    transport = _CaptureTransport()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sentry_sdk.init(
            transport=transport,
            **sentry_options(**_OPTIONS, traces_sample_rate=traces_sample_rate),
        )
    transport.init_warnings = caught
    try:
        yield transport
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)


def test_init_works_and_collects_no_pii(sentry):
    client = sentry_sdk.get_client()
    assert client.is_active()
    resolved = client.options["data_collection"]
    assert resolved["user_info"] is False
    assert resolved["cookies"] == {"mode": "off"}
    assert resolved["http_bodies"] == []
    assert resolved["queues"] is False
    assert resolved["database_query_data"] is False
    assert resolved["gen_ai"] == {"inputs": False, "outputs": False}
    assert resolved["mcp"] == {"inputs": False, "outputs": False}
    assert resolved["stack_frame_variables"]["mode"] == "denylist"
    assert client.options["attach_stacktrace"] is False
    assert "logging" in client.integrations


def test_init_raises_no_deprecation_warning(sentry):
    deprecations = [
        str(w.message)
        for w in sentry.init_warnings
        if issubclass(w.category, (DeprecationWarning, PendingDeprecationWarning, FutureWarning))
    ]
    assert deprecations == []


def test_logger_error_produces_an_event_but_info_ships_nothing(sentry):
    logger = logging.getLogger("sentry3.test")
    logger.info("routine information")
    logger.error("something broke")
    sentry_sdk.get_client().flush(timeout=2)
    events = sentry.items("event")
    assert [e["logentry"]["message"] for e in events] == ["something broke"]
    assert events[0]["level"] == "error"
    # No Sentry Logs (3.0 would ship INFO and up with the integration's default).
    assert sentry.items("log") == []


def _raise_with_secrets():
    # Built at runtime so the values do not appear in the source context lines.
    password = "hunter" + "2"  # noqa: F841 - captured as a frame variable
    api_token = "tok-" + "123"  # noqa: F841
    page = 3  # noqa: F841
    raise ValueError("boom")


def test_before_send_masks_extra_and_local_variables(sentry):
    with sentry_sdk.new_scope() as scope:
        scope.set_extra("token", "tok-" + "456")
        scope.set_extra("page", 2)
        try:
            _raise_with_secrets()
        except ValueError:
            sentry_sdk.capture_exception()
    (event,) = sentry.items("event")
    assert event["extra"]["token"] == FILTERED
    assert event["extra"]["page"] == 2
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    variables = next(f["vars"] for f in frames if f["function"] == "_raise_with_secrets")
    assert variables["password"] == FILTERED
    assert variables["api_token"] == FILTERED
    assert variables["page"] == "3"
    text = repr(event)
    assert "hunter2" not in text and "tok-123" not in text and "tok-456" not in text


def test_scrub_event_masks_request_data_headers_user_and_breadcrumbs():
    event = {
        "request": {
            "url": "https://example.test/reset?token=abc&page=2",
            "query_string": "password=pw&page=2",
            "headers": {"Authorization": "Bearer x", "Accept": "*/*"},
            "cookies": {"sessionid": "s"},
            "data": {"password": "hunter2", "nested": {"api_key": "k"}, "title": "ok"},
        },
        "extra": {"secret": "s", "page": 3, "note": "Bearer abc.def"},
        "user": {"id": "7", "ip_address": "203.0.113.9"},
        "breadcrumbs": {"values": [{"data": {"token": "abc", "n": 1}}]},
        "exception": {
            "values": [{"stacktrace": {"frames": [{"vars": {"passwd": "p", "i": "1"}}]}}]
        },
    }
    out = scrub_event(event, {})
    request = out["request"]
    assert request["url"] == "https://example.test/reset?token=[Filtered]&page=2"
    assert request["query_string"] == "password=[Filtered]&page=2"
    assert request["headers"] == {"Authorization": FILTERED, "Accept": "*/*"}
    assert request["cookies"] == {"sessionid": FILTERED}
    assert request["data"]["password"] == FILTERED
    assert request["data"]["nested"]["api_key"] == FILTERED
    assert request["data"]["title"] == "ok"
    assert out["extra"] == {"secret": FILTERED, "page": 3, "note": "Bearer [Filtered]"}
    assert out["user"] == {"id": "7"}
    assert out["breadcrumbs"]["values"][0]["data"] == {"token": FILTERED, "n": 1}
    frame = out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame["vars"] == {"passwd": FILTERED, "i": "1"}


class _Boom(dict):
    def items(self):
        raise RuntimeError("unexpected")

    def get(self, *args):
        raise RuntimeError("unexpected")


def test_scrub_event_never_raises_and_strips_on_unexpected_shape():
    frame = {"vars": {"password": "x"}}
    event = {
        "extra": _Boom(password="x"),
        "request": {"data": "x"},
        "exception": {"values": [{"stacktrace": {"frames": [frame]}}]},
        "message": "m",
    }
    out = scrub_event(event, {})
    assert set(out) == {"exception", "message"}
    assert frame == {}
    # Even the frames cannot be walked: the stack traces go too.
    out = scrub_event({"extra": _Boom(), "exception": _Boom(), "message": "m"}, {})
    assert out == {"message": "m"}


def test_scrub_span_never_raises():
    out = scrub_span({"name": "GET /?token=abc", "attributes": _Boom(token="abc")}, {})
    assert out == {"name": FILTERED, "attributes": {}}


def test_before_send_span_masks_name_and_attributes():
    span = {
        "name": "GET /api/reset/?token=abc123&page=2",
        "attributes": {
            "http.request.header.authorization": ["Bearer xyz"],
            "url.full": "https://example.test/?password=pw&page=2",
            "db.query.text": "SELECT 1",
            "sentry.op": "http.server",
        },
    }
    out = scrub_span(span, {})
    assert out["name"] == "GET /api/reset/?token=[Filtered]&page=2"
    attributes = out["attributes"]
    assert attributes["http.request.header.authorization"] == FILTERED
    assert attributes["url.full"] == "https://example.test/?password=[Filtered]&page=2"
    assert attributes["db.query.text"] == "SELECT 1"
    assert attributes["sentry.op"] == "http.server"


@pytest.mark.parametrize("sentry", [1.0], indirect=True)
def test_before_send_span_runs_on_real_spans(sentry):
    with sentry_sdk.start_span(name="job ?token=abc", attributes={"api_key": "k", "n": 1}):
        pass
    sentry_sdk.get_client().flush(timeout=2)
    spans = [
        span
        for container in sentry.items("span")
        for span in (container.get("items") if isinstance(container, dict) else None) or [container]
    ]
    assert spans, "no span envelope captured"
    text = repr(spans)
    assert "abc" not in text and "'k'" not in text
    assert "[Filtered]" in text


def test_before_send_scrubs():
    event = before_send({"extra": {"secret": "s", "n": 1}}, {})
    assert event["extra"] == {"secret": FILTERED, "n": 1}
