"""End-to-end WebSocket cycle over the Channels consumer (contract §4-§6).

Verifies the round state machine, live participation, secret-of-votes (no value
leaks before reveal), and facilitator authority.
"""
import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from decks.seed import create_standard_deck
from realtime.routing import websocket_urlpatterns
from rooms.codes import generate_token, generate_unique_code
from rooms.models import Participant, Role, Room
from rooms.snapshot import build_deck_snapshot


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
async def test_unknown_token_rejected():
    code, _, _ = await database_sync_to_async(_make_room)()
    comm = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f"/ws/rooms/{code}/")
    connected, _ = await comm.connect()
    assert connected
    await comm.send_json_to({"v": 1, "type": "session.join", "payload": {"participantToken": "bogus"}})
    msg = await comm.receive_json_from()
    assert msg["type"] == "error" and msg["payload"]["code"] == "token.unknown"
    await comm.disconnect()
