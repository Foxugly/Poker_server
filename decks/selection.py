"""Which decks a team may play with, and which one it actually plays.

Single source of truth shared by the teams API (the catalogue + the picker) and
``rooms`` (dealing a room). Keeping it here avoids the two drifting apart and a
team being offered a deck that room creation then refuses.
"""
from django.db.models import Q

from .models import CardBack, Deck

DELEGATION_POKER_CODE = "delegation_poker"


def available_decks(team=None):
    """Active decks the team may pick: every standard one, plus its own customs.

    Anonymous rooms (``team=None``) only ever see the standard decks.
    """
    qs = Deck.objects.filter(is_active=True).select_related("vote_type")
    if team is None:
        # Account-less room: the free subset only.
        return qs.filter(team__isnull=True, is_standard=True, free_tier=True).order_by("pk")
    return qs.filter(Q(team__isnull=True, is_standard=True) | Q(team=team)).order_by("-is_standard", "pk")


def available_card_backs(team=None):
    """Active card backs the team may pick: every standard one, plus its own."""
    qs = CardBack.objects.filter(is_active=True)
    if team is None:
        return qs.filter(team__isnull=True, is_standard=True, free_tier=True).order_by("pk")
    return qs.filter(Q(team__isnull=True, is_standard=True) | Q(team=team)).order_by("-is_standard", "pk")


def free_decks_by_ids(deck_ids):
    """The free decks matching these ids, in catalogue order.

    Silently drops anything not in the free catalogue rather than erroring: the
    ids come from a public, unauthenticated payload.
    """
    catalogue = list(available_decks(None))
    wanted = set(deck_ids or [])
    chosen = [d for d in catalogue if d.pk in wanted]
    return chosen or catalogue[:1]


def free_card_back_by_id(card_back_id):
    if card_back_id is None:
        return None
    return next((b for b in available_card_backs(None) if b.pk == card_back_id), None)


def card_back_for_team(team):
    """The team's picked card back, or None to fall back to the deck's own image.

    A deactivated or reassigned pick falls back too, so a stale choice can't break
    room creation.
    """
    if team is None or team.card_back_id is None:
        return None
    back = CardBack.objects.filter(pk=team.card_back_id, is_active=True).first()
    if back is not None and (back.team_id is None or back.team_id == team.pk):
        return back
    return None


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
            team.decks.filter(is_active=True)
            .filter(Q(team__isnull=True, is_standard=True) | Q(team=team))
            .select_related("vote_type")
            .order_by("-is_standard", "pk")
        )
        if enabled:
            return enabled
    standard = standard_deck()
    return [standard] if standard is not None else []
