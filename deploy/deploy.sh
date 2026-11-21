#!/usr/bin/env bash
# =============================================================================
# Delegation Poker — Deployment script (runs as 'django' via OIDC->SSM).
#   /var/www/django_websites/Poker_server/deploy/deploy.sh
# =============================================================================
set -euo pipefail
umask 027   # new dirs 750 / files 640 from git/pip/collectstatic (§3.1/§3.2)

APP_DIR="/var/www/django_websites/Poker_server"
VENV="$APP_DIR/.venv"

cd "$APP_DIR"

echo ">>> Installing dependencies..."
# requirements.txt is a hash-pinned lock (uv pip compile requirements.in, Linux /
# Python 3.12). A plain `pip install -r` never upgrades a package already
# installed inside its range, so prod silently missed releases CI had tested.
# Installing the exact lock makes prod run what CI ran; --no-deps means nothing
# is resolved on the box, and pip check fails the deploy on an incomplete lock.
"$VENV/bin/pip" install --quiet --require-hashes --no-deps -r requirements.txt
"$VENV/bin/pip" check

# Load the SSM-fetched env so manage.py has SECRET_KEY, STATE, DB creds, etc.
# Parse literally (key=value), NOT `source`: values may contain shell-special
# chars that `.` would mangle (mirrors systemd EnvironmentFile parsing).
ENV_FILE="/run/poker/.env"
if [ -f "$ENV_FILE" ]; then
    echo ">>> Loading env from $ENV_FILE..."
    while IFS='=' read -r _k _v || [ -n "$_k" ]; do
        case "$_k" in ''|\#*) continue ;; esac
        export "$_k=$_v"
    done < "$ENV_FILE"
    unset _k _v
else
    echo "WARNING: $ENV_FILE missing — has poker-env-fetch run? Trying without it." >&2
fi

echo ">>> Running migrations..."
"$VENV/bin/python" manage.py migrate --noinput

echo ">>> Collecting static files..."
"$VENV/bin/python" manage.py collectstatic --noinput

echo ">>> Seeding the standard Delegation Poker deck (idempotent)..."
"$VENV/bin/python" manage.py seed_delegation_deck || true

echo ">>> Normalizing permissions (dirs 750 / files 640, no o-rwx, no g-w)..."
chown -R django:www-data "$APP_DIR"
chmod -R g-w,o-rwx "$APP_DIR"

# poker-env-fetch is intentionally NOT restarted here (a code deploy keeps the
# env already in /run/poker/.env). To pick up changed SSM values:
#   sudo systemctl restart poker-env-fetch && sudo systemctl restart poker-asgi poker-celery poker-celery-beat
echo ">>> Restarting services..."
sudo /bin/systemctl restart poker-asgi
sudo /bin/systemctl restart poker-celery
sudo /bin/systemctl restart poker-celery-beat

echo ">>> Deploy complete."
