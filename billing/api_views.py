"""Stripe billing endpoints (P2.7), account-level. Checkout/portal/status are per-user;
the webhook is public but Stripe-signature verified. Inert until Stripe is configured."""
import logging
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api_errors import error_response
from teams.models import Team

from .models import Subscription
from .service import (
    billing_configured,
    plan_for_price,
    price_for,
    stripe_client,
    user_is_paid,
    user_quota,
)

logger = logging.getLogger("poker")
User = get_user_model()


def _sub_for(user):
    sub, _ = Subscription.objects.get_or_create(user=user)
    return sub


def _sync_from_stripe(user, stripe_sub) -> None:
    """Persist a Stripe subscription's state onto the user's Subscription row."""
    sub = _sub_for(user)
    sub.stripe_subscription_id = stripe_sub.get("id", "") or ""
    sub.status = stripe_sub.get("status", "") or ""
    customer = stripe_sub.get("customer")
    if customer:
        sub.stripe_customer_id = customer
    end = stripe_sub.get("current_period_end")
    sub.current_period_end = (
        datetime.fromtimestamp(end, tz=timezone.get_current_timezone()) if end else None
    )
    # Plan/interval from the subscription's price.
    try:
        price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    except (KeyError, IndexError, TypeError):
        price_id = ""
    plan, interval = plan_for_price(price_id)
    if plan:
        sub.plan, sub.interval = plan, interval
    sub.save()


class CheckoutView(APIView):
    """POST {plan, interval} → a Stripe Checkout Session URL to subscribe the account."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        stripe = stripe_client()
        if stripe is None:
            return error_response(code="billing_unconfigured", detail="Billing is not enabled.", http_status=503)
        plan = request.data.get("plan")
        interval = request.data.get("interval")
        price_id = price_for(plan, interval)
        if not price_id:
            return error_response(code="unknown_plan", detail="Unknown plan or interval.", http_status=400)

        sub = _sub_for(request.user)
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "client_reference_id": str(request.user.id),
            "metadata": {"user_id": str(request.user.id), "plan": plan},
            "success_url": f"{base}/teams?billing=success",
            "cancel_url": f"{base}/teams?billing=cancel",
        }
        if sub.stripe_customer_id:
            params["customer"] = sub.stripe_customer_id
        else:
            params["customer_email"] = request.user.email
        session = stripe.checkout.Session.create(**params)
        return Response({"url": session.url})


class PortalView(APIView):
    """POST → a Stripe billing-portal URL to manage/cancel the subscription."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        stripe = stripe_client()
        if stripe is None:
            return error_response(code="billing_unconfigured", detail="Billing is not enabled.", http_status=503)
        sub = _sub_for(request.user)
        if not sub.stripe_customer_id:
            return error_response(code="no_customer", detail="No subscription to manage.", http_status=400)
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        session = stripe.billing_portal.Session.create(customer=sub.stripe_customer_id, return_url=f"{base}/teams")
        return Response({"url": session.url})


class SubscriptionView(APIView):
    """GET the account's billing status (used by the SPA to show plans / quota)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sub = getattr(request.user, "subscription", None)
        quota = user_quota(request.user)
        teams_used = Team.objects.filter(owner=request.user).count()
        return Response(
            {
                "billingEnabled": billing_configured(),
                "isPaid": user_is_paid(request.user),
                "status": sub.status if sub else "",
                "plan": sub.plan if sub else "",
                "interval": sub.interval if sub else "",
                "quota": quota,
                "teamsUsed": teams_used,
                "canManage": bool(sub and sub.stripe_customer_id),
            }
        )


class WebhookView(APIView):
    """Stripe webhook: signature-verified, keeps the account subscription in sync."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        stripe = stripe_client()
        if stripe is None:
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        sig = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe.Webhook.construct_event(request.body, sig, settings.STRIPE_WEBHOOK_SECRET)
        except Exception:  # invalid payload or signature
            return Response(status=status.HTTP_400_BAD_REQUEST)

        etype = event["type"]
        obj = event["data"]["object"]
        user = self._resolve_user(obj)
        if user is None:
            return Response(status=status.HTTP_200_OK)

        if etype == "checkout.session.completed":
            sub_id = obj.get("subscription")
            if sub_id:
                _sync_from_stripe(user, stripe.Subscription.retrieve(sub_id))
        elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
            _sync_from_stripe(user, obj)
        logger.info("stripe_webhook", extra={"type": etype, "user_id": user.id})
        return Response(status=status.HTTP_200_OK)

    def _resolve_user(self, obj):
        uid = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id")
        if uid:
            return User.objects.filter(pk=uid).first()
        customer = obj.get("customer")
        if customer:
            sub = Subscription.objects.filter(stripe_customer_id=customer).select_related("user").first()
            return sub.user if sub else None
        return None
