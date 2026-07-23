"""Which decks a team may play with, and which one it actually plays.

Single source of truth shared by the teams API (the catalogue + the picker) and
``rooms`` (dealing a room). Keeping it here avoids the two drifting apart and a
team being offered a deck that room creation then refuses.
"""
from django.db.models import Q

from .models import CardBack, Deck, Felt

DELEGATION_POKER_CODE = "delegation_poker"


def squad_of(owner):
    """The set of user ids whose uploads a team of this ``owner`` may see:
    the owner, plus every manager of a team the owner owns (owner+managers, not
    plain members). An upload is visible wherever its author sits in a squad."""
    from teams.models import Team, TeamMembership, TeamRole

    team_ids = Team.objects.filter(owner=owner).values_list("pk", flat=True)
    manager_ids = TeamMembership.objects.filter(
        team_id__in=team_ids, role=TeamRole.MANAGER
    ).values_list("user_id", flat=True)
    return {owner.pk, *manager_ids}


def can_upload(user) -> bool:
    """A user may upload iff they belong to at least one squad — i.e. they own or
    manage a team (plain members can't). Teams require a paid owner, so this
    implicitly gates on a paid squad."""
    from teams.models import TeamMembership, TeamRole

    return TeamMembership.objects.filter(
        user=user, role__in=(TeamRole.OWNER, TeamRole.MANAGER)
    ).exists()


def available_decks(team=None):
    """Decks a room may play. An account-less room (``team=None``) sees the free
    subset; a team (always paid) sees the whole catalogue."""
    qs = Deck.objects.filter(is_active=True).select_related("vote_type")
    if team is None:
        return qs.filter(free_tier=True).order_by("pk")
    return qs.order_by("pk")


def available_card_backs(team=None):
    """Card backs a room may use: for an account-less room, whatever is flagged
    free_tier + active (same admin-drivable rule as decks — is_standard is NOT
    required, so a custom back can be promoted to the free offer); for a team,
    every built-in plus the squad's custom uploads."""
    qs = CardBack.objects.filter(is_active=True)
    if team is None:
        return qs.filter(free_tier=True).order_by("pk")
    squad = squad_of(team.owner)
    return qs.filter(Q(is_standard=True) | Q(is_standard=False, uploaded_by__in=squad)).order_by("is_standard", "pk")


def free_decks_by_ids(deck_ids):
    """Every free deck, with the caller's pick (if any) first.

    An account-less room always carries the WHOLE free catalogue — the facilitator
    may switch poker type round by round in-room — so the home-page pick only
    chooses the STARTING type (the first snapshot becomes the active deck).
    Unknown ids are silently ignored: they come from a public payload.
    """
    catalogue = list(available_decks(None))
    wanted = set(deck_ids or [])
    chosen = [d for d in catalogue if d.pk in wanted]
    rest = [d for d in catalogue if d.pk not in wanted]
    return chosen + rest


def free_card_back_by_id(card_back_id):
    if card_back_id is None:
        return None
    return next((b for b in available_card_backs(None) if b.pk == card_back_id), None)


def available_felts(team=None):
    """Felts a room may use: built-in ones plus the team squad's custom uploads."""
    qs = Felt.objects.filter(is_active=True)
    if team is None:
        return qs.filter(is_standard=True, free_tier=True).order_by("pk")
    squad = squad_of(team.owner)
    return qs.filter(Q(is_standard=True) | Q(is_standard=False, uploaded_by__in=squad)).order_by("is_standard", "pk")


def felt_for_team(team):
    """The team's picked felt, or None. A deactivated or reassigned pick falls back."""
    if team is None or team.felt_id is None:
        return None
    return Felt.objects.filter(pk=team.felt_id, is_active=True).first()


def card_back_for_team(team):
    """The team's picked card back, or None to fall back to the deck's own image.

    A deactivated or reassigned pick falls back too, so a stale choice can't break
    room creation.
    """
    if team is None or team.card_back_id is None:
        return None
    return CardBack.objects.filter(pk=team.card_back_id, is_active=True).first()


def standard_deck(vote_type_code: str = DELEGATION_POKER_CODE):
    return (
        Deck.objects.filter(vote_type__code=vote_type_code, is_standard=True, is_active=True)
        .select_related("vote_type")
        .first()
    )


def decks_for_team(team):
    """Every deck a new room for this team may play, in catalogue order.

    Falls back to the standard deck when the team enabled none, and drops picks
    that were since deactivated or reassigned — a stale choice must not break room
    creation. Returns [] only when no standard deck is configured at all.
    """
    if team is not None:
        enabled = list(
            team.decks.filter(is_active=True).select_related("vote_type").order_by("pk")
        )
        if enabled:
            return enabled
    standard = standard_deck()
    return [standard] if standard is not None else []
