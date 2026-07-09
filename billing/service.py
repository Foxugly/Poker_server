"""Stripe billing helpers (P2.7), account-level. Gated on the secret: when Stripe is
not configured the feature is inert — user_is_paid()/team_is_paid() return True so
teams stay open in prod until billing goes live, and checkout reports 503."""
from django.conf import settings
from django.utils import timezone

# Stripe statuses that grant access.
PAID_STATUSES = {"active", "trialing"}


def billing_configured() -> bool:
    if not settings.STRIPE_SECRET_KEY:
        return False
    return any(price for plan in settings.STRIPE_PRICES.values() for price in plan.values())


def stripe_client():
    if not billing_configured():
        return None
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def price_for(plan: str, interval: str) -> str:
    return settings.STRIPE_PRICES.get(plan, {}).get(interval, "")


def plan_for_price(price_id: str):
    """Reverse a Stripe price id → (plan, interval), or (None, None) if unknown."""
    for plan, intervals in settings.STRIPE_PRICES.items():
        for interval, pid in intervals.items():
            if pid and pid == price_id:
                return plan, interval
    return None, None


def quota_for_plan(plan: str) -> int:
    return settings.PLAN_QUOTAS.get(plan, 0)


def _active_subscription(user):
    sub = getattr(user, "subscription", None)
    if sub is None or sub.status not in PAID_STATUSES:
        return None
    if sub.current_period_end is not None and sub.current_period_end < timezone.now():
        return None
    return sub


def user_is_paid(user) -> bool:
    """Whether a user may use paid features (own teams). Inert (True) until Stripe is
    configured; then requires an active subscription."""
    if not billing_configured():
        return True
    return _active_subscription(user) is not None


def user_quota(user) -> int:
    """Max number of teams the user may own. Unlimited (large) when billing is off."""
    if not billing_configured():
        return 10_000
    sub = _active_subscription(user)
    return quota_for_plan(sub.plan) if sub else 0


def team_is_paid(team) -> bool:
    return user_is_paid(team.owner)


def paid_required(team):
    """402 error_response when the team's owner lacks an active subscription, else None.
    Inert until Stripe is configured."""
    if team_is_paid(team):
        return None
    from config.api_errors import error_response

    return error_response(
        code="subscription_required", detail="A subscription is required for this feature.", http_status=402
    )
