"""L'etat de connexion doit dire au destinataire QUI il est.

Sans cela, le client tenait son propre role de la session enregistree a son arrivee.
Prendre le role de facilitateur le rendait donc tel pour tout le monde sauf pour
lui-meme, et recharger n'y changeait rien : le role perime etait persiste. Le bouton
« prendre le role » etait, de son point de vue, sans effet.
"""
import pytest

from decks.seed import create_standard_deck
from realtime import services
from rooms.codes import generate_token, generate_unique_code
from rooms.models import Participant, Role, Room, Subject, VoteSession
from rooms.snapshot import build_deck_snapshot


def _room():
    deck = create_standard_deck()
    code = generate_unique_code(lambda c: Room.objects.filter(code=c).exists())
    room = Room(code=code, vote_type=deck.vote_type, deck_snapshot=build_deck_snapshot(deck))
    room.touch(save=False)
    room.save()
    fac = Participant.objects.create(room=room, token=generate_token(), display_name="Sam", role=Role.FACILITATOR)
    voter = Participant.objects.create(room=room, token=generate_token(), display_name="Alex", role=Role.VOTER)
    subject = Subject.objects.create(room=room, text="Deploys")
    session = VoteSession.objects.create(room=room, subject=subject, facilitator=fac)
    room.current_session = session
    room.save(update_fields=["current_session"])
    return room, fac, voter


@pytest.mark.django_db
def test_state_sync_tells_each_client_its_own_role(db):
    _r, fac, voter = _room()

    assert services.build_state_sync(fac)["myRole"] == Role.FACILITATOR
    assert services.build_state_sync(voter)["myRole"] == Role.VOTER


@pytest.mark.django_db
def test_state_sync_identifies_the_recipient(db):
    """L'identifiant permet au client de se reconnaitre dans les diffusions, qui
    designent le nouveau facilitateur par son identifiant public."""
    _r, fac, voter = _room()

    assert services.build_state_sync(voter)["myParticipantId"] == str(voter.public_id)
    assert services.build_state_sync(fac)["myParticipantId"] == str(fac.public_id)


@pytest.mark.django_db
def test_claiming_the_role_is_visible_to_the_claimer(db):
    """Le coeur du defaut : apres la prise de role, l'interesse doit se voir
    facilitateur, et l'ancien redevenir simple votant."""
    room, _fac, voter = _room()
    services.promote_facilitator(room, voter)
    room.refresh_from_db()

    assert services.build_state_sync(voter)["myRole"] == Role.FACILITATOR


@pytest.mark.django_db
def test_a_hand_over_demotes_the_giver_for_himself(db):
    """Meme trou sur la passation volontaire : celui qui donne le role doit se voir
    redevenir votant."""
    room, fac, voter = _room()
    services.transfer_facilitator(room, fac, str(voter.public_id))
    room.refresh_from_db()
    fac.refresh_from_db()
    voter.refresh_from_db()

    assert services.build_state_sync(fac)["myRole"] == Role.VOTER
    assert services.build_state_sync(voter)["myRole"] == Role.FACILITATOR


@pytest.mark.django_db
def test_claim_before_any_round_demotes_the_previous_facilitator(db):
    """Audit M6 : avant le premier sujet, il n'y a pas de session et l'autorite
    retombe sur le role. La prise de main doit donc retrograder l'ancien
    facilitateur, sinon deux participants ont l'autorite."""
    room, fac, voter = _room()
    room.current_session = None
    room.save(update_fields=["current_session"])

    services.promote_facilitator(room, voter)
    fac.refresh_from_db()
    voter.refresh_from_db()

    assert fac.role == Role.VOTER
    assert voter.role == Role.FACILITATOR
    assert list(room.participants.filter(role=Role.FACILITATOR)) == [voter]
    with pytest.raises(services.RoomError):
        services._require_facilitator(room, fac, "subject.add")
    services._require_facilitator(room, voter, "subject.add")
