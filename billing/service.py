"""Stripe billing helpers (P2.7). Gated on the secret: when Stripe is not configured
the whole feature is inert — team_is_paid() returns True so paid features stay open in
prod until billing goes live, and the checkout endpoints report 503."""
from django.conf import settings
from django.utils import timezone

# Statuses that grant access to paid features.
PAID_STATUSES = {"active", "trialing"}


def billing_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PRICE_ID)


def stripe_client():
    """Return the configured stripe module, or None when billing is off."""
    if not billing_configured():
        return None
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def paid_required(team):
    """Return a 402 error_response when the team lacks an active subscription, else None.
    Inert until Stripe is configured (team_is_paid() is then always True)."""
    if team_is_paid(team):
        return None
    from config.api_errors import error_response

    return error_response(
        code="subscription_required", detail="A subscription is required for this feature.", http_status=402
    )


def team_is_paid(team) -> bool:
    """Whether a team may use paid features. Until Stripe is configured, always True
    (features remain open); once configured, requires an active subscription that has
    not lapsed."""
    if not billing_configured():
        return True
    if team.subscription_status not in PAID_STATUSES:
        return False
    end = team.subscription_current_period_end
    return end is None or end >= timezone.now()
