"""Une couche `icon` porte une cle d'icone, pas de la prose : elle doit sortir du
snapshot en chaine simple, comme une couche `static`, et surtout PAS en dictionnaire
par langue — une cle d'icone ne se traduit pas."""
import pytest

from decks.models import TextLayer, TextLayerKind
from rooms.snapshot import build_deck_snapshot


@pytest.mark.django_db
def test_icon_layer_serialises_as_plain_string(standard_deck):
    card = standard_deck.cards.order_by("order").first()
    layer = TextLayer.objects.create(
        card=card, order=9, pos_x=50, pos_y=50, font_size=55,
        content_kind=TextLayerKind.ICON,
    )
    layer.set_current_language("en")
    layer.content = "fist-3"
    layer.save()

    snapshot = build_deck_snapshot(standard_deck)
    layers = snapshot["cards"][0]["layers"]
    icon = next(l for l in layers if l["kind"] == "icon")

    assert icon["text"] == "fist-3"
    assert isinstance(icon["text"], str)


@pytest.mark.django_db
def test_i18n_layer_still_serialises_as_a_dict(standard_deck):
    """Garde-fou de non-regression : le comportement existant ne bouge pas."""
    snapshot = build_deck_snapshot(standard_deck)
    layers = snapshot["cards"][0]["layers"]
    i18n = next(l for l in layers if l["kind"] == "i18n")

    assert isinstance(i18n["text"], dict)
    assert i18n["text"]["fr"] == "Dire"
