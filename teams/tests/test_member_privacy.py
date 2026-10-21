"""Members see each other's display name only; emails stay with the team's
managers (owner + managers) and with each member for their own row."""
import importlib

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from realtime.services import participants_list
from rooms.codes import generate_token
from rooms.models import Participant, Role, Room
from teams.models import Team, TeamMembership, TeamRole

User = get_user_model()


def _user(email, name="", first_name=""):
    return User.objects.create_user(email=email, password="pw12345678", display_name=name, first_name=first_name)


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def squad(db):
    owner = _user("owner@example.com", "Olive")
    manager = _user("manager@example.com", "Max")
    member = _user("member@example.com", "Mia")
    nameless = _user("jane.doe@example.com")
    team = Team.objects.create(name="Squad", owner=owner)
    TeamMembership.objects.create(team=team, user=owner, role=TeamRole.OWNER)
    TeamMembership.objects.create(team=team, user=manager, role=TeamRole.MANAGER)
    TeamMembership.objects.create(team=team, user=member, role=TeamRole.MEMBER)
    TeamMembership.objects.create(team=team, user=nameless, role=TeamRole.MEMBER)
    return {"team": team, "owner": owner, "manager": manager, "member": member, "nameless": nameless}


def _members(viewer, team):
    resp = _client(viewer).get(f"/api/v1/teams/{team.id}/members/")
    assert resp.status_code == 200
    return {m["user"]["id"]: m["user"] for m in resp.json()}


@pytest.mark.django_db
def test_regular_member_sees_names_but_only_own_email(squad):
    rows = _members(squad["member"], squad["team"])
    for user_id, row in rows.items():
        if user_id == squad["member"].id:
            assert row["email"] == "member@example.com"
        else:
            assert row["email"] is None
    assert "@" not in str([r["display_name"] for r in rows.values()])
    assert rows[squad["owner"].id]["display_name"] == "Olive"


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["owner", "manager"])
def test_owner_and_manager_see_every_email(squad, who):
    rows = _members(squad[who], squad["team"])
    assert rows[squad["member"].id]["email"] == "member@example.com"
    assert rows[squad["nameless"].id]["email"] == "jane.doe@example.com"


@pytest.mark.django_db
def test_role_change_response_keeps_email_for_manager(squad):
    resp = _client(squad["owner"]).patch(
        f"/api/v1/teams/{squad['team'].id}/members/{squad['member'].id}/", {"role": "manager"}, format="json"
    )
    assert resp.status_code == 200 and resp.json()["user"]["email"] == "member@example.com"


@pytest.mark.django_db
def test_nameless_member_gets_neutral_name_not_email_local_part(squad):
    nameless = squad["nameless"]
    row = _members(squad["member"], squad["team"])[nameless.id]
    assert row["display_name"] == f"Participant {nameless.id}"
    assert "jane" not in row["display_name"].lower()


@pytest.mark.django_db
def test_public_name_fallbacks(db):
    assert _user("a@example.com", "Ann").public_name == "Ann"
    assert _user("b@example.com", "", first_name="Bea").public_name == "Bea"
    typed_email = _user("c@example.com", "c@example.com", first_name="Cleo")
    assert typed_email.public_name == "Cleo"
    blank = _user("d@example.com", "  ")
    assert blank.public_name == f"Participant {blank.pk}"


@pytest.mark.django_db
def test_team_detail_no_longer_exposes_owner_email(squad):
    body = _client(squad["member"]).get(f"/api/v1/teams/{squad['team'].id}/").json()
    assert "owner_email" not in body
    assert "owner@example.com" not in str(body)


@pytest.mark.django_db
def test_team_room_seat_and_socket_roster_never_carry_email(standard_deck, squad):
    team = squad["team"]
    code = _client(squad["nameless"]).post("/api/v1/rooms", {"team": team.id}, format="json").json()["code"]
    assert _client(squad["member"]).post(f"/api/v1/rooms/{code}/join", {}, format="json").status_code == 200
    room = Room.objects.get(code=code)
    roster = participants_list(room)
    names = {p["username"] for p in roster}
    assert names == {f"Participant {squad['nameless'].id}", "Mia"}
    assert "@" not in str(roster)


@pytest.mark.django_db
def test_rejoin_renames_seat_still_named_after_email(standard_deck, squad):
    team = squad["team"]
    member = squad["member"]
    code = _client(squad["owner"]).post("/api/v1/rooms", {"team": team.id}, format="json").json()["code"]
    room = Room.objects.get(code=code)
    seat = Participant.objects.create(
        room=room, token=generate_token(), display_name=member.email, role=Role.VOTER, user=member
    )
    assert _client(member).post(f"/api/v1/rooms/{code}/join", {}, format="json").status_code == 200
    seat.refresh_from_db()
    assert seat.display_name == "Mia"


@pytest.mark.django_db
def test_migration_renames_email_named_seats(standard_deck, squad):
    migration = importlib.import_module("rooms.migrations.0009_participant_names_without_email")
    code = _client(squad["owner"]).post("/api/v1/rooms", {"team": squad["team"].id}, format="json").json()["code"]
    room = Room.objects.get(code=code)
    leaked = Participant.objects.create(
        room=room, token=generate_token(), display_name="jane.doe@example.com", role=Role.VOTER, user=squad["nameless"]
    )
    guest = Participant.objects.create(room=room, token=generate_token(), display_name="me@home", role=Role.VOTER)
    migration.forwards(apps, None)
    leaked.refresh_from_db()
    guest.refresh_from_db()
    assert leaked.display_name == f"Participant {squad['nameless'].id}"
    assert guest.display_name == "me@home"  # anonymous seat: the name its owner typed
