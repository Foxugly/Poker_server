"""Les deux decks a pictogrammes : contenu, idempotence, et exclusion de l'offre gratuite."""
import pytest
from django.core.management import call_command

from decks.models import Deck, TextLayerKind
from decks.seed import create_fist_of_five_deck, create_roman_vote_deck
from decks.selection import available_decks


@pytest.mark.django_db
def test_fist_of_five_has_six_mute_cards():
    deck = create_fist_of_five_deck()
    cards = list(deck.cards.order_by("order"))

    assert [c.value for c in cards] == ["0", "1", "2", "3", "4", "5"]
    for card in cards:
        layers = list(card.layers.all())
        assert len(layers) == 1
        assert layers[0].content_kind == TextLayerKind.ICON
        assert card.background_image.name == "decks/cards/front_cartes_foxugly.png"

    keys = [c.layers.first().safe_translation_getter("content", any_language=True) for c in cards]
    assert keys == ["fist-0", "fist-1", "fist-2", "fist-3", "fist-4", "fist-5"]


@pytest.mark.django_db
def test_roman_vote_orders_from_favourable_to_against():
    deck = create_roman_vote_deck()
    cards = list(deck.cards.order_by("order"))

    assert [c.value for c in cards] == ["+1", "0", "-1"]
    keys = [c.layers.first().safe_translation_getter("content", any_language=True) for c in cards]
    assert keys == ["thumb-up", "thumb-side", "thumb-down"]


@pytest.mark.django_db
def test_both_decks_are_reserved_to_paid_teams():
    create_fist_of_five_deck()
    create_roman_vote_deck()

    # Une salle sans compte ne voit que l'offre gratuite : ni l'un ni l'autre.
    free_codes = {d.vote_type.code for d in available_decks(None)}
    assert "fist_of_five" not in free_codes
    assert "roman_vote" not in free_codes


@pytest.mark.django_db
def test_roman_values_survive_into_the_snapshot():
    """Le « + » de « +1 » ne doit etre ni perdu ni normalise : c'est la valeur canonique
    stockee dans Vote.card_value et Result.chosen_value. `act_result` la validera par
    simple appartenance a `_card_values(room)`, donc aucun code supplementaire n'est
    necessaire — mais une valeur mangee au peuplement rendrait la carte invotable."""
    from rooms.snapshot import build_deck_snapshot

    snapshot = build_deck_snapshot(create_roman_vote_deck())
    assert [c["value"] for c in snapshot["cards"]] == ["+1", "0", "-1"]


@pytest.mark.django_db
def test_command_is_idempotent_per_vote_type():
    call_command("seed_icon_decks")
    call_command("seed_icon_decks")

    assert Deck.objects.filter(vote_type__code="fist_of_five").count() == 1
    assert Deck.objects.filter(vote_type__code="roman_vote").count() == 1
