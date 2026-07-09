"""Billing is gated on the Stripe secret. Unconfigured (tests + prod until keys are
seeded): teams stay open, quota is unbounded, and checkout reports 503."""
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from billing.service import billing_configured, plan_for_price, price_for, quota_for_plan, user_is_paid, user_quota
from teams.models import Team, TeamMembership, TeamRole

User = get_user_model()

PRICES = {
    "team1": {"monthly": "price_1m", "yearly": "price_1y"},
    "team5": {"monthly": "price_5m", "yearly": "price_5y"},
}


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="o@example.com", password="pw12345678", display_name="Owner")


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_unconfigured_billing_is_inert(owner):
    assert billing_configured() is False
    assert user_is_paid(owner) is True
    assert user_quota(owner) >= 1
    # teams can still be created freely
    assert _client(owner).post("/api/teams/", {"name": "A"}, format="json").status_code == 201
    body = _client(owner).get("/api/billing/subscription/").json()
    assert body["billingEnabled"] is False and body["isPaid"] is True


@pytest.mark.django_db
def test_checkout_portal_503_when_unconfigured(owner):
    c = _client(owner)
    assert c.post("/api/billing/checkout/", {"plan": "team1", "interval": "monthly"}, format="json").status_code == 503
    assert c.post("/api/billing/portal/", {}, format="json").status_code == 503


@pytest.mark.django_db
def test_webhook_503_when_unconfigured(db):
    assert APIClient().post("/api/billing/webhook/", {}, format="json").status_code == 503


@override_settings(STRIPE_SECRET_KEY="sk_test", STRIPE_PRICES=PRICES)
@pytest.mark.django_db
def test_configured_gates_team_creation(owner):
    # Stripe now "configured" but the user has no subscription → cannot create a team.
    assert billing_configured() is True
    assert user_is_paid(owner) is False
    assert user_quota(owner) == 0
    r = _client(owner).post("/api/teams/", {"name": "A"}, format="json")
    assert r.status_code == 402 and r.json()["code"] == "subscription_required"


@override_settings(STRIPE_SECRET_KEY="sk_test", STRIPE_PRICES=PRICES, PLAN_QUOTAS={"team1": 1, "team5": 5})
@pytest.mark.django_db
def test_quota_enforced_for_active_sub(owner):
    from billing.models import Subscription

    Subscription.objects.create(user=owner, status="active", plan="team1")
    assert user_quota(owner) == 1
    c = _client(owner)
    assert c.post("/api/teams/", {"name": "A"}, format="json").status_code == 201
    # second team exceeds the team1 quota
    r = c.post("/api/teams/", {"name": "B"}, format="json")
    assert r.status_code == 402 and r.json()["code"] == "quota_exceeded"


@override_settings(STRIPE_PRICES=PRICES)
def test_price_and_plan_mapping():
    assert price_for("team5", "yearly") == "price_5y"
    assert plan_for_price("price_1m") == ("team1", "monthly")
    assert plan_for_price("nope") == (None, None)
    assert quota_for_plan("team5") == 5
