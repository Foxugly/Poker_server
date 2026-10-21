from .base import *

DEBUG = False

# Behind nginx TLS termination (OPERATIONS.md §3.6).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# HSTS et nosniff : posés par nginx SEULEMENT (deploy/nginx/poker-api.conf).
# Les deux couches les envoyaient, avec des max-age différents (audit
# 2026-10-18, M12) — même choix que billing. nginx couvre aussi /static/,
# /media/ et ses propres pages d'erreur (502 au redémarrage de daphne), que
# Django ne voit pas. Ne pas réactiver ici sans retirer les add_header du vhost.
# `server_tokens off` est global (/etc/nginx/nginx.conf, OPERATIONS.md §3.6).
SECURE_HSTS_SECONDS = 0
SECURE_CONTENT_TYPE_NOSNIFF = False
# `check --deploy` ne voit pas nginx : W004 (HSTS) et W006 (nosniff) sont faux ici.
SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W006"]

# Shared cache for the DRF throttle counters (audit 2026-10-18, M3). The default
# LocMem cache lived in the daphne process: every restart or deploy reset the
# limits. Same Redis database as the channel layer and Celery (`REDIS_URL`,
# db 3 on the box), under its own key prefix — as on Facilitation.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://127.0.0.1:6379/0"),
        "KEY_PREFIX": "poker-cache",
    }
}
