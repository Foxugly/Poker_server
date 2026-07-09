"""Deck snapshot builder (data-model spec §4).

Serializes the editable ``decks`` referential into an immutable, self-contained JSON
blob frozen on the room at creation. The realtime layer reads only this blob, so an
admin editing a deck later never mutates a live room (scope §3.6 immutability).
"""
from django.conf import settings

from decks.models import Deck, TextLayerKind


def _media_url(image_field):
    if not image_field:
        return None
    url = image_field.url
    if url.startswith("http"):
        return url
    return f"{settings.PUBLIC_MEDIA_BASE_URL.rstrip('/')}{url}"


def _layer_text(layer):
    """Static → single string (fallback/EN row); i18n → {lang: text} across LANGUAGES."""
    if layer.content_kind == TextLayerKind.STATIC:
        return layer.safe_translation_getter("content", any_language=True) or ""
    text = {}
    for code, _ in settings.LANGUAGES:
        value = layer.safe_translation_getter("content", language_code=code, any_language=False)
        if value:
            text[code] = value
    return text


def build_deck_snapshot(deck: Deck) -> dict:
    vote_type = deck.vote_type
    cards = []
    for card in deck.cards.filter(is_active=True).prefetch_related("layers__translations").order_by("order"):
        layers = []
        for layer in card.layers.all().order_by("order"):
            layers.append(
                {
                    "kind": layer.content_kind,
                    "order": layer.order,
                    "x": float(layer.pos_x),
                    "y": float(layer.pos_y),
                    "font": layer.font_family,
                    "size": float(layer.font_size),
                    "weight": layer.font_weight,
                    "color": layer.color,
                    "align": layer.align,
                    "text": _layer_text(layer),
                }
            )
        cards.append(
            {
                "value": card.value,
                "slug": card.slug,
                "order": card.order,
                "background": {"image": _media_url(card.background_image)},
                "layers": layers,
            }
        )
    return {
        "voteType": vote_type.code,
        "resolutionStrategy": vote_type.resolution_strategy,
        "deckId": deck.pk,
        "cardBack": {"image": _media_url(deck.card_back_image)},
        # Room theme (P2.6): default appearance; team rooms override from the team.
        "theme": {"cardBackColor": DEFAULT_CARD_BACK_COLOR, "feltColor": DEFAULT_FELT_COLOR},
        "cards": cards,
    }


# Defaults mirror the frontend's built-in room look (dark card-back base, emerald felt).
DEFAULT_CARD_BACK_COLOR = "#143d2f"
DEFAULT_FELT_COLOR = "#10b981"
