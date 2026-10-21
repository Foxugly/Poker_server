"""Team-room seats used to be named after the member's email when they had no
display name, and that name is broadcast to every participant. Rename those seats
with the same fallback as ``accounts.models.public_name_for`` (frozen copy here:
a migration must not import live model code)."""
from django.db import migrations


def _public_name(user) -> str:
    for candidate in (user.display_name, user.first_name):
        name = (candidate or "").strip()
        if name and "@" not in name:
            return name[:50]
    return f"Participant {user.pk}"


def forwards(apps, schema_editor):
    Participant = apps.get_model("rooms", "Participant")
    seats = Participant.objects.filter(user__isnull=False, display_name__contains="@").select_related("user")
    for seat in seats.iterator():
        seat.display_name = _public_name(seat.user)
        seat.save(update_fields=["display_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_user_avatar"),
        ("rooms", "0008_room_result_layout"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
