"""Which decks a team may play with, and which one it actually plays.

Single source of truth shared by the teams API (the catalogue + the picker) and
``rooms`` (dealing a room). Keeping it here avoids the two drifting apart and a
team being offered a deck that room creation then refuses.
"""
from .models import CardBack, Deck, Felt

DELEGATION_POKER_CODE = "delegation_poker"


def available_decks(team=None):
    """Decks a room may play. An account-less room (``team=None``) sees the free
    subset; a team (always paid) sees the whole catalogue."""
    qs = Deck.objects.filter(is_active=True).select_related("vote_type")
    if team is None:
        return qs.filter(free_tier=True).order_by("pk")
    return qs.order_by("pk")


def available_card_backs(team=None):
    """Card backs a room may use: the free subset for an account-less room, the
    whole catalogue for a team."""
    qs = CardBack.objects.filter(is_active=True)
    if team is None:
        return qs.filter(free_tier=True).order_by("pk")
    return qs.order_by("pk")


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


def available_felts(team=None):
    """Felts a room may use: the free subset for an account-less room, the whole
    catalogue for a team."""
    qs = Felt.objects.filter(is_active=True)
    if team is None:
        return qs.filter(free_tier=True).order_by("pk")
    return qs.order_by("pk")


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
