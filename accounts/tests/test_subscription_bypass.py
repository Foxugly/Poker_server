"""Coverage of the subscription_bypass flag on the account (spec lot A).

- The field exists, defaults to False, and carries an audit note + grant date.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.mark.django_db
def test_subscription_bypass_defaults_to_false():
    user = User.objects.create_user(email="u@example.com", password="pw12345678")
    assert user.subscription_bypass is False
    assert user.bypass_note == ""
    assert user.bypass_granted_at is None


@pytest.mark.django_db
def test_subscription_bypass_is_persisted():
    user = User.objects.create_user(email="u2@example.com", password="pw12345678")
    user.subscription_bypass = True
    user.bypass_note = "early adopter"
    user.save()
    user.refresh_from_db()
    assert user.subscription_bypass is True and user.bypass_note == "early adopter"


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_me_exposes_subscription_bypass():
    user = User.objects.create_user(email="me@example.com", password="pw12345678")
    user.subscription_bypass = True
    user.save()
    r = _client(user).get("/api/auth/me/")
    assert r.status_code == 200 and r.json()["subscription_bypass"] is True


@pytest.mark.django_db
def test_patch_me_cannot_self_grant_bypass():
    """Auto-élévation : le champ est read-only, un PATCH doit être ignoré."""
    user = User.objects.create_user(email="esc@example.com", password="pw12345678")
    r = _client(user).patch("/api/auth/me/", {"subscription_bypass": True}, format="json")
    assert r.status_code == 200
    user.refresh_from_db()
    assert user.subscription_bypass is False


@pytest.mark.django_db
def test_subscription_endpoint_reports_bypass():
    user = User.objects.create_user(email="sub@example.com", password="pw12345678")
    user.subscription_bypass = True
    user.save()
    r = _client(user).get("/api/billing/subscription/")
    assert r.status_code == 200 and r.json()["bypass"] is True
