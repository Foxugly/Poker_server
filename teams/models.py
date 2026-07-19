"""Teams & membership (Phase 2 P2.2). A Team is owned by a User; members join via
a TeamMembership carrying a role. Invitations are emailed, single-use, and require
the invitee to be signed in to accept (login-required link, scope §4.1)."""
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class TeamRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"


def generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


class Team(models.Model):
    name = models.CharField(max_length=120)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_teams")
    created_at = models.DateTimeField(auto_now_add=True)
    # Appearance customization (P2.6): the team's room theme. Defaults mirror the
    # standard emerald felt + dark card-back base used by anonymous rooms.
    card_back_color = models.CharField(max_length=9, default="#143d2f")
    felt_color = models.CharField(max_length=9, default="#10b981")
    # The deck this team's rooms are dealt from. Null = the vote type's standard
    # deck (the only option until the team owns a custom one).
    deck = models.ForeignKey("decks.Deck", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # The card back, picked independently of the fronts. Null = the deck's own default.
    card_back = models.ForeignKey("decks.CardBack", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # Billing (P2.7) is account-level: a team is "paid" via its owner's
    # billing.Subscription (plan quota), not a per-team subscription.

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    role = models.CharField(max_length=12, choices=TeamRole.choices, default=TeamRole.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("team", "user"), name="uniq_membership_team_user"),
        ]

    def __str__(self):
        return f"{self.user_id}@{self.team_id} ({self.role})"


class Invitation(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=12, choices=TeamRole.choices, default=TeamRole.MEMBER)
    token = models.CharField(max_length=64, unique=True, default=generate_invite_token)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_pending(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()

    def __str__(self):
        return f"invite {self.email} -> {self.team_id}"
