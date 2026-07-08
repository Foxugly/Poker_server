from celery import shared_task
from django.utils import timezone

from .models import Room


@shared_task
def expire_stale_rooms():
    """Mark rooms inactive for > ROOM_INACTIVITY_HOURS as expired (scope §4).

    Belt-and-braces cleanup: join / WS entry already refuse an expired room
    lazily (Room.is_live); this beat task just flips the flag in the background.
    """
    count = Room.objects.filter(is_expired=False, expires_at__lt=timezone.now()).update(is_expired=True)
    return count
