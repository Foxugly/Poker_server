"""End-to-end WebSocket cycle over the Channels consumer (contract §4-§6).

Verifies the round state machine, live participation, secret-of-votes (no value
leaks before reveal), and facilitator authority.
"""
import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.utils import timezone

from decks.seed import create_standard_deck
from realtime.routing import websocket_urlpatterns
from rooms.codes import generate_token, generate_unique_code
from rooms.models import Participant, Role, Room
from rooms.snapshot import build_deck_snapshot


def _age_facilitator(code, seconds):
    """Simulate the facilitator having been absent for `seconds` (guard test)."""
    Room.objects.get(code=code).participants.filter(role=Role.FACILITATOR).update(
        is_connected=False, last_seen_at=timezone.now() - timezone.timedelta(seconds=seconds)
    )


def _role_of(token):
    return Participant.objects.get(token=token).role


def _make_room():
    deck = create_standard_deck()
    # Unique code per test: the process-global InMemoryChannelLayer keys groups by
    # code, so a shared code would leak group state across transactional tests.
    code = generate_unique_code(lambda c: Room.objects.filter(code=c).exists())
    room = Room(code=code, vote_type=deck.vote_type, deck_snapshot=build_deck_snapshot(deck), title="Retro")
    room.touch(save=False)
    room.save()
    fac = Participant.objects.create(room=room, token=generate_token(), display_name="Sam", role=Role.FACILITATOR)
    voter = Participant.objects.create(room=room, token=generate_token(), display_name="Alex", role=Role.VOTER)
    return code, fac.token, voter.token


async def _join(token, code):
    comm = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f"/ws/rooms/{code}/")
    connected, _ = await comm.connect()
    assert connected
    await comm.send_json_to({"v": 1, "type": "session.join", "payload": {"participantToken": token}})
    first = await comm.receive_json_from()
    assert first["type"] == "state.sync"
    return comm, first


async def _drain_until(comm, wanted, pred=None, limit=8):
    for _ in range(limit):
        msg = await comm.receive_json_from()
        if msg["type"] == wanted and (pred is None or pred(msg["payload"])):
            return msg
    raise AssertionError(f"{wanted} not received")


@pytest.mark.django_db(transaction=True)
async def test_full_vote_cycle_and_secret_of_votes():
    code, fac_token, voter_token = await database_sync_to_async(_make_room)()

    fac, fac_sync = await _join(fac_token, code)
    assert fac_sync["payload"]["roundState"] == "idle"
    assert len(fac_sync["payload"]["deckSnapshot"]["cards"]) == 7

    voter, _ = await _join(voter_token, code)
    await _drain_until(fac, "participant.joined")

    await fac.send_json_to({"v": 1, "type": "subject.set", "payload": {"text": "Who owns the budget?"}})
    await _drain_until(voter, "subject.updated")
    await fac.send_json_to({"v": 1, "type": "vote.open", "payload": {}})
    await _drain_until(voter, "vote.opened")

    # voter casts — participation updates carry IDs/counts, NEVER values (secret §6.a)
    await voter.send_json_to({"v": 1, "type": "vote.cast", "payload": {"cardValue": "5"}})
    part = await _drain_until(fac, "participation.update", pred=lambda p: p["voted"] == 1)
    # Secret of votes (§6.a): participation carries only counts + participant IDs,
    # never a card value — the payload has exactly these three keys.
    assert set(part["payload"].keys()) == {"voted", "total", "votedIds"}
    assert part["payload"]["total"] == 2

    # facilitator reveals → values now visible
    await fac.send_json_to({"v": 1, "type": "vote.reveal", "payload": {}})
    revealed = await _drain_until(voter, "vote.revealed")
    assert revealed["payload"]["votes"][0]["cardValue"] == "5"
    assert revealed["payload"]["spread"] == {"min": 5, "max": 5}

    await fac.send_json_to({"v": 1, "type": "result.act", "payload": {"chosenValue": "5"}})
    acted = await _drain_until(voter, "result.acted")
    assert acted["payload"]["chosenValue"] == "5"

    await fac.disconnect()
    await voter.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_voter_cannot_open_vote_authority():
    code, fac_token, voter_token = await database_sync_to_async(_make_room)()
    fac, _ = await _join(fac_token, code)
    voter, _ = await _join(voter_token, code)
    await fac.send_json_to({"v": 1, "type": "subject.set", "payload": {"text": "X"}})

    # a voter trying a control intention is rejected, not applied
    await voter.send_json_to({"v": 1, "type": "vote.open", "payload": {}})
    err = await _drain_until(voter, "error")
    assert err["payload"]["code"] == "forbidden.not_facilitator"

    await fac.disconnect()
    await voter.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_reconnection_restores_vote_and_state():
    code, fac_token, voter_token = await database_sync_to_async(_make_room)()
    fac, _ = await _join(fac_token, code)
    voter, _ = await _join(voter_token, code)
    await _drain_until(fac, "participant.joined")

    await fac.send_json_to({"v": 1, "type": "subject.set", "payload": {"text": "Budget?"}})
    await _drain_until(voter, "subject.updated")
    await fac.send_json_to({"v": 1, "type": "vote.open", "payload": {}})
    await _drain_until(voter, "vote.opened")
    await voter.send_json_to({"v": 1, "type": "vote.cast", "payload": {"cardValue": "3"}})
    await _drain_until(fac, "participation.update", pred=lambda p: p["voted"] == 1)

    # Network drop + reconnect with the same token restores room + vote (contract §8).
    await voter.disconnect()
    voter2, sync2 = await _join(voter_token, code)
    assert sync2["payload"]["roundState"] == "open"
    assert sync2["payload"]["myVote"] == "3"

    await fac.disconnect()
    await voter2.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_facilitator_guard_and_takeover():
    code, fac_token, voter_token = await database_sync_to_async(_make_room)()
    fac, _ = await _join(fac_token, code)
    voter, _ = await _join(voter_token, code)
    await _drain_until(fac, "participant.joined")

    # Facilitator drops → others learn presence=false.
    await fac.disconnect()
    await _drain_until(voter, "facilitator.presence", pred=lambda p: p["present"] is False)

    # A claim within the 60s grace is rejected (a blip must not cost the role).
    await voter.send_json_to({"v": 1, "type": "facilitator.claim", "payload": {}})
    err = await _drain_until(voter, "error")
    assert err["payload"]["code"] == "guard.inactive"

    # After the grace elapses, the first claimer takes over.
    await database_sync_to_async(_age_facilitator)(code, 61)
    await voter.send_json_to({"v": 1, "type": "facilitator.claim", "payload": {}})
    changed = await _drain_until(voter, "facilitator.changed")
    assert changed["payload"]["newFacilitatorId"]
    assert await database_sync_to_async(_role_of)(voter_token) == Role.FACILITATOR

    await voter.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_agenda_add_and_select():
    code, fac_token, _ = await database_sync_to_async(_make_room)()
    fac, _ = await _join(fac_token, code)

    await fac.send_json_to({"v": 1, "type": "subject.add", "payload": {"text": "Q1"}})
    await _drain_until(fac, "agenda.updated")
    await fac.send_json_to({"v": 1, "type": "subject.add", "payload": {"text": "Q2"}})
    a2 = await _drain_until(fac, "agenda.updated", pred=lambda p: len(p["agenda"]) == 2)
    agenda = a2["payload"]["agenda"]
    assert [x["text"] for x in agenda] == ["Q1", "Q2"]
    assert agenda[0]["status"] == "current" and agenda[1]["status"] == "pending"

    await fac.send_json_to({"v": 1, "type": "subject.select", "payload": {"subjectId": agenda[1]["id"]}})
    a3 = await _drain_until(fac, "agenda.updated", pred=lambda p: p["agenda"][1]["status"] == "current")
    assert a3["payload"]["agenda"][1]["status"] == "current" and a3["payload"]["agenda"][0]["status"] == "pending"

    await fac.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_facilitator_voluntary_transfer():
    code, fac_token, voter_token = await database_sync_to_async(_make_room)()
    fac, _ = await _join(fac_token, code)
    voter, vsync = await _join(voter_token, code)
    await _drain_until(fac, "participant.joined")

    voter_pid = next(p["participantId"] for p in vsync["payload"]["participants"] if p["role"] == "voter")
    await fac.send_json_to({"v": 1, "type": "facilitator.transfer", "payload": {"targetParticipantId": voter_pid}})
    changed = await _drain_until(voter, "facilitator.changed")
    assert changed["payload"]["newFacilitatorId"] == voter_pid
    assert await database_sync_to_async(_role_of)(voter_token) == Role.FACILITATOR
    assert await database_sync_to_async(_role_of)(fac_token) == Role.VOTER

    await fac.disconnect()
    await voter.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_unknown_token_rejected():
    code, _, _ = await database_sync_to_async(_make_room)()
    comm = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f"/ws/rooms/{code}/")
    connected, _ = await comm.connect()
    assert connected
    await comm.send_json_to({"v": 1, "type": "session.join", "payload": {"participantToken": "bogus"}})
    msg = await comm.receive_json_from()
    assert msg["type"] == "error" and msg["payload"]["code"] == "token.unknown"
    await comm.disconnect()
