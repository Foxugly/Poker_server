"""Synchronous domain logic for the realtime room (data-model spec §5.4, contract §4-§6).

Kept sync + framework-light so it is unit-testable without a socket; the consumer
wraps these with ``database_sync_to_async``. Server is the source of truth: every
mutation validates the state machine and raises ``RoomError`` on an illegal move
(contract §0.1, §6.b) rather than applying it.
"""
from django.conf import settings
from django.utils import timezone

from rooms.models import (
    Participant,
    Result,
    Role,
    Room,
    RoundState,
    Subject,
    Vote,
    VoteSession,
)


class RoomError(Exception):
    def __init__(self, code, message="", rejected_type=None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.rejected_type = rejected_type


def _card_values(room):
    return {card["value"] for card in room.deck_snapshot.get("cards", [])}


def resolve_participant(code, token):
    """token → participant (+ room). Returns None if unknown/expired (contract §3)."""
    participant = (
        Participant.objects.select_related("room")
        .filter(room__code=code, token=token)
        .first()
    )
    if participant is None:
        return None
    if not participant.room.is_live:
        return None
    return participant


def set_connected(participant, connected):
    participant.is_connected = connected
    participant.last_seen_at = timezone.now()
    participant.save(update_fields=["is_connected", "last_seen_at"])


def _current_session(room):
    return room.current_session


def _require_facilitator(room, participant, rejected_type):
    session = _current_session(room)
    # Authority is the session facilitator; before any session exists, the room's
    # sole facilitator participant holds it (contract §2).
    if session and session.facilitator_id:
        if participant.id != session.facilitator_id:
            raise RoomError("forbidden.not_facilitator", "Not the facilitator", rejected_type)
    elif participant.role != Role.FACILITATOR:
        raise RoomError("forbidden.not_facilitator", "Not the facilitator", rejected_type)


def touch(room):
    room.touch()


def set_subject(room, participant, text):
    _require_facilitator(room, participant, "subject.set")
    session = _current_session(room)
    if session and session.state == RoundState.IDLE:
        session.subject.text = text
        session.subject.save(update_fields=["text"])
    else:
        seq = room.subjects.count() + 1
        subject = Subject.objects.create(room=room, text=text, sequence=seq)
        session = VoteSession.objects.create(
            room=room, subject=subject, state=RoundState.IDLE, facilitator=participant
        )
        room.current_session = session
        room.save(update_fields=["current_session"])
    room.touch()
    return text


def open_vote(room, participant):
    _require_facilitator(room, participant, "vote.open")
    session = _current_session(room)
    if session is None or not session.subject.text.strip():
        raise RoomError("state.invalid_transition", "No subject set", "vote.open")
    if session.state != RoundState.IDLE:
        raise RoomError("state.invalid_transition", "Not idle", "vote.open")
    session.state = RoundState.OPEN
    session.opened_at = timezone.now()
    session.save(update_fields=["state", "opened_at"])
    room.touch()


def cast_vote(room, participant, card_value):
    session = _current_session(room)
    if session is None or session.state != RoundState.OPEN:
        raise RoomError("state.invalid_transition", "Voting is not open", "vote.cast")
    if card_value not in _card_values(room):
        raise RoomError("state.invalid_transition", "Unknown card value", "vote.cast")
    Vote.objects.update_or_create(
        session=session, participant=participant, defaults={"card_value": card_value}
    )
    room.touch()


def reveal(room, participant):
    _require_facilitator(room, participant, "vote.reveal")
    session = _current_session(room)
    if session is None or session.state != RoundState.OPEN:
        raise RoomError("state.invalid_transition", "Not open", "vote.reveal")
    if not session.votes.exists():
        raise RoomError("state.invalid_transition", "No votes yet", "vote.reveal")
    session.state = RoundState.REVEALED
    session.revealed_at = timezone.now()
    session.save(update_fields=["state", "revealed_at"])
    room.touch()


def act_result(room, participant, chosen_value):
    _require_facilitator(room, participant, "result.act")
    session = _current_session(room)
    if session is None or session.state != RoundState.REVEALED:
        raise RoomError("state.invalid_transition", "Not revealed", "result.act")
    if chosen_value not in _card_values(room):
        raise RoomError("state.invalid_transition", "Unknown card value", "result.act")
    Result.objects.update_or_create(
        session=session,
        defaults={"subject": session.subject, "chosen_value": chosen_value, "decided_by": participant},
    )
    session.state = RoundState.ACTED
    session.save(update_fields=["state"])
    room.touch()
    return chosen_value


def reset_round(room, participant):
    _require_facilitator(room, participant, "vote.reset")
    session = _current_session(room)
    if session is None:
        raise RoomError("state.invalid_transition", "No round", "vote.reset")
    session.votes.all().delete()
    session.state = RoundState.IDLE
    session.opened_at = None
    session.revealed_at = None
    session.save(update_fields=["state", "opened_at", "revealed_at"])
    room.touch()
    return "idle"


def participation(room):
    session = _current_session(room)
    total = room.participants.count()
    if session is None:
        return {"voted": 0, "total": total, "votedIds": []}
    voted_ids = list(
        Vote.objects.filter(session=session).values_list("participant__public_id", flat=True)
    )
    return {"voted": len(voted_ids), "total": total, "votedIds": [str(pid) for pid in voted_ids]}


def revealed_payload(room):
    """Vote values — ONLY ever called in REVEALED state (secret-of-votes, contract §6.a)."""
    session = _current_session(room)
    votes = list(
        Vote.objects.filter(session=session).select_related("participant")
    )
    items = [{"participantId": str(v.participant.public_id), "cardValue": v.card_value} for v in votes]
    numeric = [int(v.card_value) for v in votes if v.card_value.isdigit()]
    spread = {"min": min(numeric), "max": max(numeric)} if numeric else {"min": None, "max": None}
    return {"votes": items, "spread": spread}


def participants_list(room):
    session = _current_session(room)
    voted = set()
    if session:
        voted = set(
            Vote.objects.filter(session=session).values_list("participant_id", flat=True)
        )
    out = []
    for p in room.participants.all():
        out.append(
            {
                "participantId": str(p.public_id),
                "username": p.display_name,
                "role": p.role,
                "hasVoted": p.id in voted,
            }
        )
    return out


def facilitator_present(room):
    session = _current_session(room)
    fac_id = session.facilitator_id if session else None
    if fac_id is None:
        return any(p.role == Role.FACILITATOR and p.is_connected for p in room.participants.all())
    fac = room.participants.filter(id=fac_id).first()
    return bool(fac and fac.is_connected)


def build_state_sync(participant):
    """Full current-state snapshot for a single client (contract §5.1). No history replay."""
    room = participant.room
    session = _current_session(room)
    my_vote = None
    result = None
    round_state = RoundState.IDLE
    subject_text = ""
    if session:
        round_state = session.state
        subject_text = session.subject.text
        vote = Vote.objects.filter(session=session, participant=participant).first()
        my_vote = vote.card_value if vote else None
        if session.state == RoundState.ACTED and hasattr(session, "result"):
            result = session.result.chosen_value

    payload = {
        "room": {"code": room.code, "title": room.title},
        "protocolVersion": 1,
        "roundState": round_state,
        "subject": subject_text,
        "deckSnapshot": room.deck_snapshot,
        "participants": participants_list(room),
        "myVote": my_vote,
        "result": result,
        "facilitatorPresent": facilitator_present(room),
    }
    # A latecomer arriving in REVEALED sees the results (contract §5.1, §6.e).
    if round_state == RoundState.REVEALED:
        payload["votes"] = revealed_payload(room)["votes"]
    return payload
