"""Endpoints staff d'administration du flag subscription_bypass (spec lot A §A.4).

- Lecture et mutation réservées à is_staff (IsAdminUser).
- L'activation horodate bypass_granted_at ; la désactivation le laisse en place.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def staff(db):
    return User.objects.create_user(email="staff@example.com", password="pw12345678", is_staff=True)


@pytest.fixture
def member(db):
    return User.objects.create_user(email="member@example.com", password="pw12345678", display_name="Mimi")


@pytest.mark.django_db
def test_staff_can_search_users(staff, member):
    r = _client(staff).get("/api/staff/users/?q=member")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1 and results[0]["email"] == "member@example.com"
    assert results[0]["subscription_bypass"] is False


@pytest.mark.django_db
def test_non_staff_cannot_search_users(member):
    r = _client(member).get("/api/staff/users/?q=member")
    assert r.status_code == 403


@pytest.mark.django_db
def test_anonymous_cannot_search_users(member):
    r = APIClient().get("/api/staff/users/?q=member")
    assert r.status_code == 401


@pytest.mark.django_db
def test_staff_grants_bypass_and_stamps_granted_at(staff, member):
    r = _client(staff).patch(
        f"/api/staff/users/{member.pk}/",
        {"subscription_bypass": True, "bypass_note": "asso X"},
        format="json",
    )
    assert r.status_code == 200, r.json()
    member.refresh_from_db()
    assert member.subscription_bypass is True
    assert member.bypass_note == "asso X"
    assert member.bypass_granted_at is not None


@pytest.mark.django_db
def test_revoking_bypass_keeps_granted_at(staff, member):
    _client(staff).patch(f"/api/staff/users/{member.pk}/", {"subscription_bypass": True}, format="json")
    member.refresh_from_db()
    granted = member.bypass_granted_at
    assert granted is not None
    _client(staff).patch(f"/api/staff/users/{member.pk}/", {"subscription_bypass": False}, format="json")
    member.refresh_from_db()
    assert member.subscription_bypass is False and member.bypass_granted_at == granted


@pytest.mark.django_db
def test_non_staff_cannot_grant_bypass(member):
    other = User.objects.create_user(email="other@example.com", password="pw12345678")
    r = _client(member).patch(f"/api/staff/users/{other.pk}/", {"subscription_bypass": True}, format="json")
    assert r.status_code == 403
    other.refresh_from_db()
    assert other.subscription_bypass is False
