from .base import *  # noqa: F401,F403

DEBUG = False

# Deterministic, dependency-free tests.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CELERY_TASK_ALWAYS_EAGER = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Effectively disable DRF rate-limiting in tests: the throttle cache (LocMem)
# persists across tests in one process, so repeated register/login calls would
# spuriously 429. Keep every scope key (ScopedRateThrottle KeyErrors on a missing
# one) but set an unreachable rate.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {k: "100000/min" for k in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]},  # noqa: F405
}
