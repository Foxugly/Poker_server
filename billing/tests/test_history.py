"""Billing history endpoint — subscriptions + invoices proxied from Stripe.

Nothing is mirrored locally, so the tests pin the two behaviours that matter:
the payload shape, and that a Stripe problem degrades instead of 500-ing.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from billing.models import Subscription

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="u@example.com", password="pw12345678", display_name="U")


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _FakeStripe:
    """Minimal stand-in for the two list calls the view makes."""

    def __init__(self, subs=None, invoices=None, raises=False):
        self._subs, self._invoices, self._raises = subs or [], invoices or [], raises
        self.Subscription = self._Lister(self._subs, raises)
        self.Invoice = self._Lister(self._invoices, raises)

    class _Lister:
        def __init__(self, data, raises):
            self._data, self._raises = data, raises

        def list(self, **kwargs):
            if self._raises:
                raise RuntimeError("stripe is down")
            return {"data": self._data}


@pytest.mark.django_db
def test_anonymous_is_rejected():
    assert APIClient().get("/api/billing/history/").status_code == 401


@pytest.mark.django_db
def test_empty_when_the_user_never_subscribed(client):
    resp = client.get("/api/billing/history/")

    assert resp.status_code == 200
    assert resp.json()["subscriptions"] == []
    assert resp.json()["invoices"] == []


@pytest.mark.django_db
def test_returns_subscriptions_and_invoices(client, user, monkeypatch, settings):
    Subscription.objects.create(user=user, stripe_customer_id="cus_1")
    settings.STRIPE_PRICES = {"team1": {"monthly": "price_m", "yearly": ""}}
    fake = _FakeStripe(
        subs=[{
            "id": "sub_1", "status": "canceled", "start_date": 1_700_000_000,
            "current_period_end": 1_700_600_000, "canceled_at": 1_700_600_000,
            "items": {"data": [{"price": {"id": "price_m"}}]},
        }],
        invoices=[{
            "id": "in_1", "number": "F-001", "status": "paid", "amount_paid": 500,
            "currency": "eur", "created": 1_700_000_000,
            "hosted_invoice_url": "https://stripe.test/i/1", "invoice_pdf": "https://stripe.test/i/1.pdf",
        }],
    )
    monkeypatch.setattr("billing.api_views.stripe_client", lambda: fake)

    body = client.get("/api/billing/history/").json()

    assert body["subscriptions"][0]["plan"] == "team1"
    assert body["subscriptions"][0]["status"] == "canceled"
    assert body["subscriptions"][0]["canceledAt"] is not None
    inv = body["invoices"][0]
    assert (inv["number"], inv["amountPaid"], inv["currency"]) == ("F-001", 500, "EUR")
    assert inv["pdfUrl"].endswith(".pdf")


@pytest.mark.django_db
def test_a_stripe_failure_degrades_instead_of_500(client, user, monkeypatch):
    """The page must still render if Stripe is unreachable."""
    Subscription.objects.create(user=user, stripe_customer_id="cus_1")
    monkeypatch.setattr("billing.api_views.stripe_client", lambda: _FakeStripe(raises=True))

    resp = client.get("/api/billing/history/")

    assert resp.status_code == 200
    assert resp.json() == {"billingEnabled": True, "subscriptions": [], "invoices": []}


@pytest.mark.django_db
def test_another_users_history_is_never_returned(client, monkeypatch):
    """The customer id comes from the authenticated user, never from the request."""
    other = User.objects.create_user(email="other@example.com", password="pw12345678")
    Subscription.objects.create(user=other, stripe_customer_id="cus_other")
    fake = _FakeStripe(invoices=[{"id": "in_x", "number": "SECRET", "created": 1}])
    monkeypatch.setattr("billing.api_views.stripe_client", lambda: fake)

    # The caller has no subscription of their own → nothing, despite Stripe having data.
    assert client.get("/api/billing/history/").json()["invoices"] == []
