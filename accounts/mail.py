"""Transactional email helper. Uses Django's email framework so the backend is
swappable via EMAIL_BACKEND (console in dev; SMTP/Graph in prod). Best-effort —
a send failure never breaks the request flow."""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("poker")


def send_email(*, to: str, subject: str, body: str) -> None:
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@poker.foxugly.com")
    try:
        send_mail(subject, body, from_email, [to], fail_silently=False)
        logger.info("email_sent", extra={"to": to, "subject": subject})
    except Exception:
        logger.exception("email_send_failed", extra={"to": to})
