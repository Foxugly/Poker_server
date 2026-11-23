# CLAUDE.md

Poker_server — Delegation Poker backend (Django + DRF + Channels, **ASGI/daphne**, `127.0.0.1:8006`,
`poker-api.foxugly.com`). Architecture, apps and local dev: `README.md`. Fleet/ops model: the
user-level `~/.claude/CLAUDE.md` and `foxugly-ops/OPERATIONS.md`.

## Commands

```bash
.venv/Scripts/python -m pytest -q          # whole suite (CI: PostgreSQL 16, --cov-fail-under=88)
ruff check .                               # ruff==0.17.6, as in CI
.venv/Scripts/python manage.py check       # includes the admin_2fa.E00x checks
```

## Admin 2FA

`/admin/` requires a TOTP second factor for **every** staff account (django-otp 1.7.5 + qrcode 8.2,
app `admin_2fa/`, fleet reference implementation). API/JWT users see nothing of it.

- **Wiring**: `"admin_2fa.apps.OTPAdminConfig"` *replaces* `"django.contrib.admin"` (it makes
  `admin.site` an `Admin2FASite`, whose `has_permission` also needs `user.is_verified()`); plus
  `django_otp`, `otp_totp`, `otp_static`, `admin_2fa` in INSTALLED_APPS and
  `django_otp.middleware.OTPMiddleware` right after `AuthenticationMiddleware`. `OTP_TOTP_ISSUER` is
  the label in the authenticator app. A missing piece fails `manage.py check` (`admin_2fa.E001-E004`).
- **Flow**: password on `/admin/login/` → `/admin/2fa/setup/` (first time: QR code + key, confirm one
  code, 10 single-use backup codes shown **once**) or `/admin/2fa/verify/` (TOTP code or a backup
  code). Server-rendered admin templates, CSRF, `never_cache`, no inline script/style.
- **Brute force**: django-otp throttles each device (1 s, 2 s, 4 s… after each wrong code) and nginx
  puts `/admin/2fa/` in the same `poker_admin_login` zone as the login (10 r/min per IP).
- **Lost phone / locked out** (on the box, as the app's own unit would run it):

  ```bash
  sudo systemd-run --wait --pipe --quiet --uid=django --gid=www-data \
    -p EnvironmentFile=/run/poker/.env -p WorkingDirectory=/var/www/django_websites/Poker_server \
    /var/www/django_websites/Poker_server/.venv/bin/python manage.py admin_2fa_reset <email>
  ```

  deletes the user's devices (re-enrolment at the next admin login); `--unlock` only clears the delay.
- **Tests on admin pages**: use `admin_2fa.testing.force_admin_login(client, user)`, not
  `client.force_login` (the admin would redirect to the second factor).
- **Secrets**: never log or send to Sentry the TOTP key, the QR code or a backup code — the views keep
  them in `Redacted` wrappers and the form field is named `token` (scrubbed by Sentry).
