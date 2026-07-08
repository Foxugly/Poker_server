"""Runtime models for a Delegation Poker room (data-model spec §5).

Identity is a per-participant secret ``token`` (spec P5); the deck is a frozen
``deck_snapshot`` JSON on the room (spec §4); a round is a ``VoteSession`` whose
``state`` runs idle → open → revealed → acted (spec §5.4).
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    FACILITATOR = "facilitator", "Facilitator"
    VOTER = "voter", "Voter"


class RoundState(models.TextChoices):
    IDLE = "idle", "Idle"
    OPEN = "open", "Open"
    REVEALED = "revealed", "Revealed"
    ACTED = "acted", "Acted"


class Room(models.Model):
    code = models.CharField(max_length=8, unique=True)  # UPPER, ambiguous chars excluded
    title = models.CharField(max_length=120, blank=True)
    vote_type = models.ForeignKey("decks.VoteType", on_delete=models.PROTECT)
    deck_snapshot = models.JSONField()  # frozen at creation, immutable (spec §4)
    current_session = models.ForeignKey(
        "rooms.VoteSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    is_expired = models.BooleanField(default=False)

    def touch(self, *, save=True):
        """Slide the 8h inactivity window forward (scope §4)."""
        now = timezone.now()
        self.last_activity_at = now
        self.expires_at = now + timezone.timedelta(hours=settings.ROOM_INACTIVITY_HOURS)
        if save:
            self.save(update_fields=["last_activity_at", "expires_at"])

    @property
    def is_live(self):
        return not self.is_expired and self.expires_at > timezone.now()

    def __str__(self):
        return self.code


class Participant(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="participants")
    token = models.CharField(max_length=64, unique=True)  # secret, replayed on each WS (re)connect
    public_id = models.UUIDField(default=uuid.uuid4, editable=False)  # broadcast id (≠ token)
    display_name = models.CharField(max_length=50)  # ephemeral display name, NOT an auth identifier
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.VOTER)
    is_connected = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(  # Phase 2 (authenticated member); nullable now
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("room", "public_id"), name="uniq_participant_room_pubid"),
        ]

    def __str__(self):
        return f"{self.display_name} ({self.role})"


class Subject(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="subjects")
    text = models.CharField(max_length=300)
    sequence = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("room", "sequence")

    def __str__(self):
        return self.text


class VoteSession(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="sessions")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="sessions")
    state = models.CharField(max_length=10, choices=RoundState.choices, default=RoundState.IDLE)
    facilitator = models.ForeignKey(
        Participant, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    opened_at = models.DateTimeField(null=True, blank=True)
    revealed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Session<{self.pk}> {self.state}"


class Vote(models.Model):
    session = models.ForeignKey(VoteSession, on_delete=models.CASCADE, related_name="votes")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="votes")
    card_value = models.CharField(max_length=32)  # ∈ snapshot cards[].value; secret until reveal
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("session", "participant"), name="uniq_vote_session_participant"),
        ]

    def __str__(self):
        return f"Vote<{self.pk}> p={self.participant_id}"


class Result(models.Model):
    session = models.OneToOneField(VoteSession, on_delete=models.CASCADE, related_name="result")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="results")
    chosen_value = models.CharField(max_length=32)
    decided_by = models.ForeignKey(Participant, on_delete=models.SET_NULL, null=True, blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Result<{self.pk}> {self.chosen_value}"
