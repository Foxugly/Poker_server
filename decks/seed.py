"""Create the standard Delegation Poker deck (7 cards, 2 layers each).

Used by tests and by the ``seed_delegation_deck`` management command. Image fields are
set to placeholder names by default — the original illustrations are a non-technical
content dependency (scope §10); the code is ready before the artwork exists.
"""
from decks.models import Card, CardBack, Deck, TextLayer, TextLayerKind, VoteType

LEVELS = [
    ("1", "tell", "Tell", "Dire", "Vertellen", "Dire", "Decir"),
    ("2", "sell", "Sell", "Vendre", "Verkopen", "Vendere", "Vender"),
    ("3", "consult", "Consult", "Consulter", "Raadplegen", "Consultare", "Consultar"),
    ("4", "agree", "Agree", "S'accorder", "Afspreken", "Concordare", "Acordar"),
    ("5", "advise", "Advise", "Conseiller", "Adviseren", "Consigliare", "Aconsejar"),
    ("6", "inquire", "Inquire", "S'enquérir", "Informeren", "Informarsi", "Indagar"),
    ("7", "delegate", "Delegate", "Déléguer", "Delegeren", "Delegare", "Delegar"),
]
LANG_ORDER = ("en", "fr", "nl", "it", "es")


def create_standard_card_back():
    """The standard back, catalogued separately so a team can pair any back with
    any deck. Seeded on its own: an install predating CardBack already has the
    deck, so seeding only inside create_standard_deck() would never reach it."""
    back, created = CardBack.objects.get_or_create(
        is_standard=True, team=None, defaults={"image": "decks/backs/back.webp", "name": "Standard"}
    )
    return back, created


def create_standard_deck():
    vt, _ = VoteType.objects.get_or_create(
        code="delegation_poker", defaults={"resolution_strategy": "delegation_v1"}
    )
    vt.set_current_language("en")
    vt.name = "Delegation Poker"
    vt.save()

    deck = Deck.objects.create(
        vote_type=vt, is_standard=True, card_back_image="decks/backs/back.webp"
    )
    deck.set_current_language("en")
    deck.name = "Delegation Poker"
    deck.save()

    create_standard_card_back()

    for value, slug, *names in LEVELS:
        card = Card.objects.create(
            deck=deck, value=value, slug=slug, order=int(value),
            background_image=f"decks/cards/{slug}.webp",
        )
        num = TextLayer.objects.create(
            card=card, order=1, pos_x=12, pos_y=12, font_size=9, font_weight=700,
            content_kind=TextLayerKind.STATIC,
        )
        num.set_current_language("en")
        num.content = value
        num.save()

        name_layer = TextLayer.objects.create(
            card=card, order=2, pos_x=50, pos_y=82, font_size=7, font_weight=600,
            content_kind=TextLayerKind.I18N,
        )
        for lang, text in zip(LANG_ORDER, names):
            name_layer.set_current_language(lang)
            name_layer.content = text
            name_layer.save()
    return deck
