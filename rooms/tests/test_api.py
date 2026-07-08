import pytest
from rest_framework.test import APIClient

from rooms.models import Participant, Role, Room


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
def test_create_room_returns_token_and_snapshot(client, standard_deck):
    resp = client.post("/api/rooms", {"title": "Retro", "username": "Sam"}, format="json")
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["code"]) == 6
    assert body["role"] == Role.FACILITATOR
    assert body["participantToken"]
    assert body["deckSnapshot"]["voteType"] == "delegation_poker"
    assert len(body["deckSnapshot"]["cards"]) == 7

    room = Room.objects.get(code=body["code"])
    assert room.title == "Retro"
    fac = Participant.objects.get(token=body["participantToken"])
    assert fac.role == Role.FACILITATOR and fac.display_name == "Sam"


@pytest.mark.django_db
def test_create_room_without_deck_is_503(client):
    resp = client.post("/api/rooms", {"username": "Sam"}, format="json")
    assert resp.status_code == 503


@pytest.mark.django_db
def test_join_room_case_insensitive(client, standard_deck):
    code = client.post("/api/rooms", {"username": "Sam"}, format="json").json()["code"]
    resp = client.post(f"/api/rooms/{code.lower()}/join", {"username": "Alex"}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == Role.VOTER
    assert body["participantToken"]
    assert len(body["deckSnapshot"]["cards"]) == 7


@pytest.mark.django_db
def test_join_unknown_room_404(client, standard_deck):
    resp = client.post("/api/rooms/ZZZZZZ/join", {"username": "Alex"}, format="json")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_room_exists_endpoint(client, standard_deck):
    code = client.post("/api/rooms", {"username": "Sam", "title": "Retro"}, format="json").json()["code"]
    assert client.get(f"/api/rooms/{code}").json() == {"code": code, "roomTitle": "Retro", "exists": True}
    assert client.get("/api/rooms/ZZZZZZ").json()["exists"] is False


@pytest.mark.django_db
def test_snapshot_layer_text_static_vs_i18n(client, standard_deck):
    body = client.post("/api/rooms", {"username": "Sam"}, format="json").json()
    card = body["deckSnapshot"]["cards"][0]
    layers = {layer["order"]: layer for layer in card["layers"]}
    assert layers[1]["kind"] == "static" and layers[1]["text"] == "1"
    assert layers[2]["kind"] == "i18n"
    assert layers[2]["text"]["en"] == "Tell" and layers[2]["text"]["fr"] == "Dire"
