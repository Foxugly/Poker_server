"""Deck catalogue + per-team deck pick (P2.8).

Covers what the picker must never allow: playing another team's custom deck, and
a stale pick breaking room creation.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from decks.models import CardBack, Deck
from decks.selection import card_back_for_team, deck_for_team
from teams.models import Team, TeamMembership, TeamRole

User = get_user_model()


def _user(email):
    return User.objects.create_user(email=email, password="pw12345678", display_name=email.split("@")[0])


@pytest.fixture
def owner(db):
    return _user("owner@example.com")


@pytest.fixture
def team(db, owner):
    t = Team.objects.create(name="Acme", owner=owner)
    TeamMembership.objects.create(team=t, user=owner, role=TeamRole.OWNER)
    return t


@pytest.fixture
def client(owner):
    c = APIClient()
    c.force_authenticate(owner)
    return c


def _custom_deck(team, vote_type, name="Custom"):
    deck = Deck.objects.create(vote_type=vote_type, team=team, is_standard=False, card_back_image="decks/backs/b.webp")
    deck.set_current_language("en")
    deck.name = name
    deck.save()
    return deck


@pytest.mark.django_db
def test_catalogue_lists_standard_deck_and_defaults_to_it(client, team, standard_deck):
    resp = client.get(f"/api/teams/{team.pk}/decks/")
    assert resp.status_code == 200
    body = resp.json()
    assert [d["id"] for d in body["decks"]] == [standard_deck.pk]
    assert body["selected_deck_id"] is None
    assert body["decks"][0]["is_custom"] is False
    assert len(body["decks"][0]["cards"]) == 7


@pytest.mark.django_db
def test_catalogue_includes_own_custom_deck_but_not_another_teams(client, team, owner, standard_deck):
    mine = _custom_deck(team, standard_deck.vote_type, "Mine")
    other_team = Team.objects.create(name="Other", owner=_user("other@example.com"))
    theirs = _custom_deck(other_team, standard_deck.vote_type, "Theirs")

    ids = [d["id"] for d in client.get(f"/api/teams/{team.pk}/decks/").json()["decks"]]
    assert mine.pk in ids
    assert theirs.pk not in ids


@pytest.mark.django_db
def test_pick_deck_and_reset_to_standard(client, team, standard_deck):
    mine = _custom_deck(team, standard_deck.vote_type)

    resp = client.patch(f"/api/teams/{team.pk}/", {"deck_id": mine.pk}, format="json")
    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.deck_id == mine.pk

    resp = client.patch(f"/api/teams/{team.pk}/", {"deck_id": None}, format="json")
    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.deck_id is None


@pytest.mark.django_db
def test_cannot_pick_another_teams_deck(client, team, standard_deck):
    other_team = Team.objects.create(name="Other", owner=_user("other@example.com"))
    theirs = _custom_deck(other_team, standard_deck.vote_type)

    resp = client.patch(f"/api/teams/{team.pk}/", {"deck_id": theirs.pk}, format="json")
    assert resp.status_code == 400
    assert resp.json()["code"] == "deck_unavailable"
    team.refresh_from_db()
    assert team.deck_id is None


@pytest.mark.django_db
def test_non_member_cannot_read_catalogue(team, standard_deck):
    c = APIClient()
    c.force_authenticate(_user("stranger@example.com"))
    assert c.get(f"/api/teams/{team.pk}/decks/").status_code == 403


@pytest.mark.django_db
def test_room_is_dealt_from_the_picked_deck(client, team, standard_deck):
    mine = _custom_deck(team, standard_deck.vote_type)
    team.deck = mine
    team.save(update_fields=["deck"])

    resp = client.post("/api/rooms", {"title": "Sprint", "team": team.pk}, format="json")
    assert resp.status_code == 201
    assert resp.json()["deckSnapshot"]["deckId"] == mine.pk


@pytest.mark.django_db
def test_deactivated_pick_falls_back_to_standard(team, standard_deck):
    """A stale pick must not break room creation — it silently falls back."""
    mine = _custom_deck(team, standard_deck.vote_type)
    team.deck = mine
    team.save(update_fields=["deck"])
    Deck.objects.filter(pk=mine.pk).update(is_active=False)

    assert deck_for_team(team).pk == standard_deck.pk


@pytest.mark.django_db
def test_untranslated_custom_deck_serializes_instead_of_500(client, team, standard_deck):
    """A deck with no row in the active language must degrade, not raise."""
    deck = Deck.objects.create(
        vote_type=standard_deck.vote_type, team=team, is_standard=False, card_back_image="decks/backs/b.webp"
    )
    deck.set_current_language("it")
    deck.name = "Mazzo"
    deck.save()

    resp = client.get(f"/api/teams/{team.pk}/decks/", HTTP_ACCEPT_LANGUAGE="en")
    assert resp.status_code == 200
    entry = next(d for d in resp.json()["decks"] if d["id"] == deck.pk)
    assert entry["name"] == "Mazzo"


@pytest.mark.django_db
def test_deck_str_prefers_english_then_french_then_technical(team, standard_deck):
    """Admin label (decks/deck/ changelist)."""
    vt = standard_deck.vote_type

    both = Deck.objects.create(vote_type=vt, team=team, card_back_image="b.webp")
    both.set_current_language("fr"); both.name = "Jeu"; both.save()
    both.set_current_language("en"); both.name = "Deck"; both.save()
    assert str(both) == "Deck"

    fr_only = Deck.objects.create(vote_type=vt, team=team, card_back_image="b.webp")
    fr_only.set_current_language("fr"); fr_only.name = "Jeu FR"; fr_only.save()
    assert str(fr_only) == "Jeu FR"

    it_only = Deck.objects.create(vote_type=vt, team=team, card_back_image="b.webp")
    it_only.set_current_language("it"); it_only.name = "Mazzo"; it_only.save()
    assert str(it_only) == f"Deck<{it_only.pk}> ({vt.pk})"

    bare = Deck.objects.create(vote_type=vt, team=team, card_back_image="b.webp")
    assert str(bare) == f"Deck<{bare.pk}> ({vt.pk})"


def _custom_back(team, name="Custom back"):
    back = CardBack.objects.create(team=team, is_standard=False, image="decks/backs/custom.webp")
    back.set_current_language("en")
    back.name = name
    back.save()
    return back


@pytest.mark.django_db
def test_catalogue_lists_card_backs_independently(client, team, standard_deck):
    mine = _custom_back(team)
    other = Team.objects.create(name="Other", owner=_user("other2@example.com"))
    theirs = _custom_back(other, "Theirs")

    body = client.get(f"/api/teams/{team.pk}/decks/").json()
    ids = [b["id"] for b in body["card_backs"]]
    assert mine.pk in ids
    assert theirs.pk not in ids
    assert body["selected_card_back_id"] is None


@pytest.mark.django_db
def test_back_and_deck_are_picked_independently(client, team, standard_deck):
    back = _custom_back(team)
    resp = client.patch(f"/api/teams/{team.pk}/", {"card_back_id": back.pk}, format="json")
    assert resp.status_code == 200
    team.refresh_from_db()
    # Picking a back leaves the fronts untouched.
    assert team.card_back_id == back.pk
    assert team.deck_id is None


@pytest.mark.django_db
def test_cannot_pick_another_teams_card_back(client, team, standard_deck):
    other = Team.objects.create(name="Other", owner=_user("other3@example.com"))
    theirs = _custom_back(other)

    resp = client.patch(f"/api/teams/{team.pk}/", {"card_back_id": theirs.pk}, format="json")
    assert resp.status_code == 400
    assert resp.json()["code"] == "card_back_unavailable"


@pytest.mark.django_db
def test_room_snapshot_uses_the_picked_back_over_the_deck_default(client, team, standard_deck):
    back = _custom_back(team)
    team.card_back = back
    team.save(update_fields=["card_back"])

    resp = client.post("/api/rooms", {"title": "Sprint", "team": team.pk}, format="json")
    assert resp.status_code == 201
    assert resp.json()["deckSnapshot"]["cardBack"]["image"].endswith("custom.webp")


@pytest.mark.django_db
def test_room_snapshot_falls_back_to_deck_default_back(client, team, standard_deck):
    resp = client.post("/api/rooms", {"title": "Sprint", "team": team.pk}, format="json")
    assert resp.status_code == 201
    assert resp.json()["deckSnapshot"]["cardBack"]["image"].endswith("back.webp")


@pytest.mark.django_db
def test_deactivated_back_pick_falls_back(team, standard_deck):
    back = _custom_back(team)
    team.card_back = back
    team.save(update_fields=["card_back"])
    CardBack.objects.filter(pk=back.pk).update(is_active=False)

    assert card_back_for_team(team) is None
