"""Billing is gated on the Stripe secret. In tests (and prod until keys are seeded)
Stripe is unconfigured: paid features stay open and the checkout endpoints report 503."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from billing.service import billing_configured, team_is_paid
from teams.models import Team, TeamMembership, TeamRole

User = get_user_model()


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="o@example.com", password="pw12345678", display_name="Owner")


@pytest.fixture
def team(owner):
    t = Team.objects.create(name="Squad", owner=owner)
    TeamMembership.objects.create(team=t, user=owner, role=TeamRole.OWNER)
    return t


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_unconfigured_billing_keeps_features_open(team, owner):
    assert billing_configured() is False
    assert team_is_paid(team) is True
    # the team serializer reflects it
    body = _client(owner).get(f"/api/teams/{team.id}/").json()
    assert body["is_paid"] is True and body["billing_enabled"] is False


@pytest.mark.django_db
def test_checkout_and_portal_503_when_unconfigured(team, owner):
    c = _client(owner)
    assert c.post("/api/billing/checkout/", {"teamId": team.id}, format="json").status_code == 503
    assert c.post("/api/billing/portal/", {"teamId": team.id}, format="json").status_code == 503


@pytest.mark.django_db
def test_webhook_503_when_unconfigured(db):
    assert APIClient().post("/api/billing/webhook/", {}, format="json").status_code == 503


@pytest.mark.django_db
def test_checkout_requires_auth(team):
    assert APIClient().post("/api/billing/checkout/", {"teamId": team.id}, format="json").status_code == 401
