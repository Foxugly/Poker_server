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


TIMER_MIN_SECONDS = 10
TIMER_MAX_SECONDS = 60
TIMER_STEP_SECONDS = 5


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


def current_subject_text(room):
    s = _current_session(room)
    return s.subject.text if s else ""


def build_agenda(room):
    """The scenario: every subject of the room with its status (current / done / pending)
    and, when acted, its retained value."""
    current_id = room.current_session.subject_id if room.current_session_id else None
    out = []
    for s in room.subjects.all().order_by("sequence").prefetch_related("sessions__result"):
        result = None
        acted = next((se for se in s.sessions.all() if se.state == RoundState.ACTED and hasattr(se, "result")), None)
        if acted:
            result = acted.result.chosen_value
        status = "current" if s.id == current_id else ("done" if result is not None else "pending")
        out.append({"id": s.id, "text": s.text, "status": status, "result": result})
    return out


def add_subject(room, participant, text):
    """Add a subject to the scenario. The first one auto-becomes the current vote."""
    _require_facilitator(room, participant, "subject.add")
    text = (text or "").strip()
    if not text:
        raise RoomError("state.invalid_transition", "Empty subject", "subject.add")
    seq = room.subjects.count() + 1
    subject = Subject.objects.create(room=room, text=text, sequence=seq)
    if room.current_session_id is None:
        session = VoteSession.objects.create(room=room, subject=subject, state=RoundState.IDLE, facilitator=participant)
        room.current_session = session
        room.save(update_fields=["current_session"])
    room.touch()
    return subject.id


def select_subject(room, participant, subject_id):
    """Pick a scenario subject to vote on next → resets the round to idle for it."""
    _require_facilitator(room, participant, "subject.select")
    subject = room.subjects.filter(id=subject_id).first()
    if subject is None:
        raise RoomError("state.invalid_transition", "Unknown subject", "subject.select")
    session = subject.sessions.exclude(state=RoundState.ACTED).first()
    if session is None:
        session = VoteSession.objects.create(room=room, subject=subject, state=RoundState.IDLE, facilitator=participant)
    else:
        session.state = RoundState.IDLE
        session.opened_at = None
        session.revealed_at = None
        session.facilitator = participant
        session.save(update_fields=["state", "opened_at", "revealed_at", "facilitator"])
        session.votes.all().delete()
    room.current_session = session
    room.save(update_fields=["current_session"])
    room.touch()
    return subject.text


def set_timer(room, participant, enabled, seconds):
    """Reglage du timer par le facilitateur. La duree est normalisee cote serveur
    (arrondi au multiple de 5 le plus proche, puis bornage 10-60) : un client
    modifie ne peut imposer ni 0 s, ni une valeur absurde, ni un pas hors grille."""
    _require_facilitator(room, participant, "timer.set")
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = room.timer_seconds
    seconds = round(seconds / TIMER_STEP_SECONDS) * TIMER_STEP_SECONDS
    seconds = max(TIMER_MIN_SECONDS, min(TIMER_MAX_SECONDS, seconds))
    room.timer_enabled = bool(enabled)
    room.timer_seconds = seconds
    room.save(update_fields=["timer_enabled", "timer_seconds"])
    room.touch()
    return {"enabled": room.timer_enabled, "seconds": room.timer_seconds}


def open_vote(room, participant):
    _require_facilitator(room, participant, "vote.open")
    session = _current_session(room)
    if session is None or not session.subject.text.strip():
        raise RoomError("state.invalid_transition", "No subject set", "vote.open")
    if session.state != RoundState.IDLE:
        raise RoomError("state.invalid_transition", "Not idle", "vote.open")
    session.state = RoundState.OPEN
    session.opened_at = timezone.now()
    session.vote_deadline = (
        session.opened_at + timezone.timedelta(seconds=room.timer_seconds)
        if room.timer_enabled
        else None
    )
    session.save(update_fields=["state", "opened_at", "vote_deadline"])
    room.touch()
    return session.vote_deadline


def cast_vote(room, participant, card_value):
    session = _current_session(room)
    if session is None or session.state != RoundState.OPEN:
        raise RoomError("state.invalid_transition", "Voting is not open", "vote.cast")
    if session.vote_deadline is not None and timezone.now() > session.vote_deadline:
        raise RoomError("state.invalid_transition", "Voting time is over", "vote.cast")
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
    session.vote_deadline = None
    session.save(update_fields=["state", "opened_at", "revealed_at", "vote_deadline"])
    room.touch()
    return "idle"


def deadline_iso(room):
    """Echeance du round courant au format ISO, ou None. Sert aux payloads WS."""
    session = _current_session(room)
    if session is None or session.vote_deadline is None:
        return None
    return session.vote_deadline.isoformat()


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


def _facilitator_participant(room):
    session = _current_session(room)
    if session and session.facilitator_id:
        return room.participants.filter(id=session.facilitator_id).first()
    return room.participants.filter(role=Role.FACILITATOR).first()


def facilitator_present(room):
    fac = _facilitator_participant(room)
    return bool(fac and fac.is_connected)


def can_claim(room):
    """Guard (contract §6.f): the takeover opens only once the facilitator has been
    absent for FACILITATOR_GUARD_SECONDS. Enforced at claim-time (no background timer),
    so a brief network blip within the grace period does NOT cost the facilitator the role."""
    fac = _facilitator_participant(room)
    if fac is None:
        return True
    if fac.is_connected:
        return False
    return (timezone.now() - fac.last_seen_at).total_seconds() >= settings.FACILITATOR_GUARD_SECONDS


def promote_facilitator(room, participant):
    """First claimer becomes facilitator. Authority is by session.facilitator, so the
    old facilitator returning is a plain voter (definitive transfer, §6.f) — no token
    reissue needed since control is keyed on participant identity, not a secret."""
    session = _current_session(room)
    if session:
        session.facilitator = participant
        session.save(update_fields=["facilitator"])
    participant.role = Role.FACILITATOR
    participant.save(update_fields=["role"])


def transfer_facilitator(room, participant, target_public_id):
    """Voluntary hand-over (contract §9, Phase 2): the current facilitator gives the
    role to another present participant and becomes a voter."""
    _require_facilitator(room, participant, "facilitator.transfer")
    target = room.participants.filter(public_id=target_public_id).first()
    if target is None or target.id == participant.id:
        raise RoomError("state.invalid_transition", "Unknown or self target", "facilitator.transfer")
    session = _current_session(room)
    if session:
        session.facilitator = target
        session.save(update_fields=["facilitator"])
    target.role = Role.FACILITATOR
    target.save(update_fields=["role"])
    participant.role = Role.VOTER
    participant.save(update_fields=["role"])
    return str(target.public_id)


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
        "agenda": build_agenda(room),
    }
    # A latecomer arriving in REVEALED sees the results (contract §5.1, §6.e).
    if round_state == RoundState.REVEALED:
        payload["votes"] = revealed_payload(room)["votes"]
    return payload
