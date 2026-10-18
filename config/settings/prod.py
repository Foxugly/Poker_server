from .base import *  # noqa: F401,F403

DEBUG = False

# Behind nginx TLS termination (OPERATIONS.md §3.6).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Shared cache for the DRF throttle counters (audit 2026-10-18, M3). The default
# LocMem cache lived in the daphne process: every restart or deploy reset the
# limits. Same Redis database as the channel layer and Celery (`REDIS_URL`,
# db 3 on the box), under its own key prefix — as on Facilitation.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://127.0.0.1:6379/0"),  # noqa: F405
        "KEY_PREFIX": "poker-cache",
    }
}
