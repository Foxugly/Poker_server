from .base import *  # noqa: F401,F403

DEBUG = True

# No Redis needed for local dev: run Channels on the in-memory layer.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Run Celery tasks synchronously in dev (no worker/broker required).
CELERY_TASK_ALWAYS_EAGER = True
