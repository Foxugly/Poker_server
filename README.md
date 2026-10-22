# Poker_server — Delegation Poker (backend)

Django + DRF + **Django Channels** (ASGI/WebSocket) backend for **Delegation Poker Online**
(Management 3.0). Part of the Foxugly fleet — conventions in `foxugly-ops/OPERATIONS.md`.

> **Fleet exception:** this is the only site that runs under an **ASGI** server (daphne),
> not gunicorn/WSGI, because Channels needs it (README-handoff §4). The realtime brick is
> isolated in the `realtime` app + `config/asgi.py`.

## Stack

Django 6 · DRF · Channels + Redis · django-parler (i18n in DB) · Celery · PostgreSQL (prod) ·
simplejwt (Phase 2 auth). Python 3.14, port `127.0.0.1:8006`.

## Apps

| App | Role |
|-----|------|
| `accounts` | Email-only `User` (no username, §3.16) — created now, auth features are Phase 2. |
| `decks` | Editable referential: `VoteType` / `Deck` / `Card` / `TextLayer` (parler translations). |
| `rooms` | Runtime: `Room` / `Participant` / `Subject` / `VoteSession` / `Vote` / `Result` + HTTP API. |
| `realtime` | Channels consumer + domain services (state machine, authority, secret votes). |
| `health` | `/health/` (status + DB check). |

## Local dev

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py runserver   # ASGI via daphne (Channels)
```

Dev uses sqlite + the in-memory channel layer (no Redis needed). Tests: `.venv/Scripts/python -m pytest`.

## Docs

- `docs/superpowers/specs/2026-07-08-data-model.md` — detailed data model (livrable n°0).
- Product scope / realtime contract / Phase-1 design: `../Poker_handoff/` (to be versioned here).

## Refresh token transport (web SPA)

Same design as PushIT (PushIT_server #69). With `X-Auth-Mode: cookie` (sent only by the SPA,
with `withCredentials`), login / magic-link verify / email confirm / `token/refresh/` put the
refresh token in an `HttpOnly; Secure; SameSite=Lax` cookie (`poker_refresh`,
`Path=/api/v1/auth/`, host-only, `Max-Age` = refresh lifetime, or a session cookie for
`remember_me: false`) and omit it from the body. Refresh reads the cookie when the body has none;
logout and account deletion clear it (logout needs no Bearer in cookie mode). Every cookie-mode
request must carry an `Origin` in `CORS_ALLOWED_ORIGINS` (403 `origin_not_allowed`); CORS allows
credentials for that explicit list only, plus the `x-auth-mode` header. Without the header the
body-token contract is unchanged. The WebSocket is untouched: it authenticates with the room
participant token in `session.join`, never a JWT. Code: `accounts/refresh_cookie.py`.

Reuse grace: a refresh token rotated less than `AUTH_REFRESH_REUSE_GRACE_SECONDS` ago (30 s, `0`
disables) is accepted **once** more, cookie mode only, from the same client (IP + User-Agent), if its
successor was never used nor revoked; the successor is then blacklisted and a new pair issued. It covers
a reload during the boot refresh that drops the rotated `Set-Cookie`. State lives in the cache (Redis in
prod). Code: `accounts/refresh_grace.py`.
