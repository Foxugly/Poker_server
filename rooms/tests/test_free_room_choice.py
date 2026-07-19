"""Deck/back choice for an account-less room.

No Team exists to persist the choice, so it travels in the create payload and is
frozen in the room's snapshots. The catalogue offered is the free subset only —
`free_tier`, which is distinct from `is_standard` (who owns the deck).
"""
import pytest
from rest_framework.test import APIClient

from decks.models import CardBack, Deck


def _extra_deck(vote_type, *, free_tier, name="Extra"):
    """A common deck (owned by nobody) that may or may not be in the free offer."""
    deck = Deck.objects.create(
        vote_type=vote_type, is_standard=True, free_tier=free_tier, card_back_image="decks/backs/b.webp"
    )
    deck.set_current_language("en")
    deck.name = name
    deck.save()
    deck.cards.create(value="13", slug="thirteen", order=1, background_image="decks/cards/13.webp")
    return deck


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
def test_catalogue_is_public_and_lists_only_the_free_subset(client, standard_deck):
    paid_only = _extra_deck(standard_deck.vote_type, free_tier=False, name="Paid only")
    free_extra = _extra_deck(standard_deck.vote_type, free_tier=True, name="Free extra")

    resp = client.get("/api/decks/catalogue/")

    assert resp.status_code == 200  # no auth required
    ids = [d["id"] for d in resp.json()["decks"]]
    assert free_extra.pk in ids
    assert paid_only.pk not in ids


@pytest.mark.django_db
def test_room_freezes_the_picked_free_decks(client, standard_deck):
    extra = _extra_deck(standard_deck.vote_type, free_tier=True)

    resp = client.post(
        "/api/rooms",
        {"title": "Retro", "username": "Alex", "deck_ids": [standard_deck.pk, extra.pk]},
        format="json",
    )

    assert resp.status_code == 201
    assert {d["deckId"] for d in resp.json()["availableDecks"]} == {standard_deck.pk, extra.pk}


@pytest.mark.django_db
def test_a_paid_only_deck_cannot_be_smuggled_in(client, standard_deck):
    """The ids come from an unauthenticated payload — they are filtered, not trusted."""
    paid_only = _extra_deck(standard_deck.vote_type, free_tier=False)

    resp = client.post(
        "/api/rooms",
        {"title": "Retro", "username": "Alex", "deck_ids": [paid_only.pk]},
        format="json",
    )

    assert resp.status_code == 201
    ids = {d["deckId"] for d in resp.json()["availableDecks"]}
    assert paid_only.pk not in ids
    assert ids == {standard_deck.pk}  # fell back to the free catalogue


@pytest.mark.django_db
def test_no_choice_falls_back_to_the_first_free_deck(client, standard_deck):
    resp = client.post("/api/rooms", {"title": "Retro", "username": "Alex"}, format="json")

    assert resp.status_code == 201
    assert resp.json()["deckSnapshot"]["deckId"] == standard_deck.pk


@pytest.mark.django_db
def test_picked_free_card_back_wins_over_the_deck_default(client, standard_deck):
    back = CardBack.objects.create(is_standard=True, free_tier=True, image="decks/backs/picked.webp")
    back.set_current_language("en")
    back.name = "Picked"
    back.save()

    resp = client.post(
        "/api/rooms", {"title": "Retro", "username": "Alex", "card_back_id": back.pk}, format="json"
    )

    assert resp.status_code == 201
    assert resp.json()["deckSnapshot"]["cardBack"]["image"].endswith("picked.webp")


@pytest.mark.django_db
def test_a_paid_only_card_back_is_ignored(client, standard_deck):
    back = CardBack.objects.create(is_standard=True, free_tier=False, image="decks/backs/paid.webp")
    back.set_current_language("en")
    back.name = "Paid"
    back.save()

    resp = client.post(
        "/api/rooms", {"title": "Retro", "username": "Alex", "card_back_id": back.pk}, format="json"
    )

    assert resp.status_code == 201
    assert resp.json()["deckSnapshot"]["cardBack"]["image"].endswith("back.webp")  # deck default
