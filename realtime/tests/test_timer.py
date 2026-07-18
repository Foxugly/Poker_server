"""Timer de round : reglage facilitateur, echeance posee a l'ouverture, votes tardifs refuses."""
import pytest
from django.utils import timezone

from realtime import services
from realtime.services import RoomError
from rooms.codes import generate_token, generate_unique_code
from rooms.models import Participant, Role, Room, RoundState
from rooms.snapshot import build_deck_snapshot


@pytest.fixture
def room_with_facilitator(standard_deck):
    """A room with a facilitator and a voter participant, mirroring test_consumer._make_room."""
    code = generate_unique_code(lambda c: Room.objects.filter(code=c).exists())
    room = Room(
        code=code,
        vote_type=standard_deck.vote_type,
        deck_snapshot=build_deck_snapshot(standard_deck),
        title="Retro",
    )
    room.touch(save=False)
    room.save()
    facilitator = Participant.objects.create(
        room=room, token=generate_token(), display_name="Sam", role=Role.FACILITATOR
    )
    voter = Participant.objects.create(
        room=room, token=generate_token(), display_name="Alex", role=Role.VOTER
    )
    return room, facilitator, voter


@pytest.mark.django_db
def test_timer_defaults_to_disabled_at_ten_seconds(room_with_facilitator):
    room, facilitator, _ = room_with_facilitator
    assert room.timer_enabled is False and room.timer_seconds == 10


@pytest.mark.django_db
def test_set_timer_requires_facilitator(room_with_facilitator):
    room, _, voter = room_with_facilitator
    with pytest.raises(RoomError):
        services.set_timer(room, voter, True, 30)


@pytest.mark.django_db
def test_set_timer_clamps_out_of_range(room_with_facilitator):
    room, facilitator, _ = room_with_facilitator
    assert services.set_timer(room, facilitator, True, 5)["seconds"] == 10
    assert services.set_timer(room, facilitator, True, 9999)["seconds"] == 60


@pytest.mark.django_db
def test_set_timer_snaps_to_five_second_steps(room_with_facilitator):
    room, facilitator, _ = room_with_facilitator
    assert services.set_timer(room, facilitator, True, 37)["seconds"] == 35
    assert services.set_timer(room, facilitator, True, 38)["seconds"] == 40
    assert services.set_timer(room, facilitator, True, 15)["seconds"] == 15


@pytest.mark.django_db
def test_open_vote_sets_no_deadline_when_disabled(room_with_facilitator):
    room, facilitator, _ = room_with_facilitator
    services.set_subject(room, facilitator, "Recrutement")
    assert services.open_vote(room, facilitator) is None
    assert services._current_session(room).vote_deadline is None


@pytest.mark.django_db
def test_open_vote_sets_deadline_when_enabled(room_with_facilitator):
    room, facilitator, _ = room_with_facilitator
    services.set_timer(room, facilitator, True, 30)
    services.set_subject(room, facilitator, "Recrutement")
    before = timezone.now()
    deadline = services.open_vote(room, facilitator)
    assert deadline is not None
    delta = (deadline - before).total_seconds()
    assert 29 <= delta <= 31


@pytest.mark.django_db
def test_vote_after_deadline_is_refused(room_with_facilitator):
    room, facilitator, voter = room_with_facilitator
    services.set_timer(room, facilitator, True, 30)
    services.set_subject(room, facilitator, "Recrutement")
    services.open_vote(room, facilitator)
    session = services._current_session(room)
    session.vote_deadline = timezone.now() - timezone.timedelta(seconds=1)
    session.save(update_fields=["vote_deadline"])
    with pytest.raises(RoomError):
        services.cast_vote(room, voter, "4")


@pytest.mark.django_db
def test_reset_clears_the_deadline(room_with_facilitator):
    room, facilitator, _ = room_with_facilitator
    services.set_timer(room, facilitator, True, 30)
    services.set_subject(room, facilitator, "Recrutement")
    services.open_vote(room, facilitator)
    services.reset_round(room, facilitator)
    assert services._current_session(room).vote_deadline is None
    assert services._current_session(room).state == RoundState.IDLE


@pytest.mark.django_db
def test_select_subject_clears_stale_deadline_after_reveal(room_with_facilitator):
    """Reveal puis re-selection du meme sujet : la session repasse IDLE et ne doit
    conserver aucune echeance perimee en base (hygiene de donnees)."""
    room, facilitator, voter = room_with_facilitator
    services.set_timer(room, facilitator, True, 30)
    services.set_subject(room, facilitator, "Recrutement")
    subject_id = services._current_session(room).subject_id
    services.open_vote(room, facilitator)
    assert services._current_session(room).vote_deadline is not None
    services.cast_vote(room, voter, "4")
    services.reveal(room, facilitator)

    services.select_subject(room, facilitator, subject_id)

    session = services._current_session(room)
    assert session.state == RoundState.IDLE
    assert session.vote_deadline is None


@pytest.mark.django_db
def test_deadline_iso_hides_stale_deadline_outside_open_round(room_with_facilitator):
    """Defense en profondeur : meme si une echeance traine en base sur une session
    non-OPEN, deadline_iso() ne doit jamais la divulguer."""
    room, facilitator, _ = room_with_facilitator
    services.set_subject(room, facilitator, "Recrutement")
    session = services._current_session(room)
    assert session.state == RoundState.IDLE
    session.vote_deadline = timezone.now() + timezone.timedelta(seconds=30)
    session.save(update_fields=["vote_deadline"])

    assert services.deadline_iso(room) is None
