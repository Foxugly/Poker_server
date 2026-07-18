"""Coverage of the subscription_bypass flag on the account (spec lot A).

- The field exists, defaults to False, and carries an audit note + grant date.
"""
import pytest
from django.contrib.auth import get_user_model

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
