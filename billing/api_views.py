"""Stripe billing endpoints (P2.7). Checkout + portal are admin-gated; the webhook is
public but Stripe-signature verified. All inert until Stripe is configured (503)."""
import logging
from datetime import datetime

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api_errors import error_response
from teams.models import Team
from teams.permissions import is_admin

from .service import billing_configured, stripe_client

logger = logging.getLogger("poker")


def _sync_subscription(team, sub) -> None:
    """Persist a Stripe subscription's state onto the team."""
    team.stripe_subscription_id = sub.get("id", "") or ""
    team.subscription_status = sub.get("status", "") or ""
    end = sub.get("current_period_end")
    team.subscription_current_period_end = (
        datetime.fromtimestamp(end, tz=timezone.get_current_timezone()) if end else None
    )
    customer = sub.get("customer")
    if customer:
        team.stripe_customer_id = customer
    team.save(
        update_fields=[
            "stripe_subscription_id",
            "subscription_status",
            "subscription_current_period_end",
            "stripe_customer_id",
        ]
    )


class CheckoutView(APIView):
    """POST {teamId} → a Stripe Checkout Session URL to subscribe the team."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        stripe = stripe_client()
        if stripe is None:
            return error_response(code="billing_unconfigured", detail="Billing is not enabled.", http_status=503)
        team = get_object_or_404(Team, pk=request.data.get("teamId"))
        if not is_admin(team, request.user):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)

        base = settings.FRONTEND_BASE_URL.rstrip("/")
        params = {
            "mode": "subscription",
            "line_items": [{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
            "client_reference_id": str(team.id),
            "metadata": {"team_id": str(team.id)},
            "success_url": f"{base}/teams/{team.id}?billing=success",
            "cancel_url": f"{base}/teams/{team.id}?billing=cancel",
        }
        if team.stripe_customer_id:
            params["customer"] = team.stripe_customer_id
        else:
            params["customer_email"] = request.user.email
        session = stripe.checkout.Session.create(**params)
        return Response({"url": session.url})


class PortalView(APIView):
    """POST {teamId} → a Stripe billing-portal URL to manage/cancel the subscription."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        stripe = stripe_client()
        if stripe is None:
            return error_response(code="billing_unconfigured", detail="Billing is not enabled.", http_status=503)
        team = get_object_or_404(Team, pk=request.data.get("teamId"))
        if not is_admin(team, request.user):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)
        if not team.stripe_customer_id:
            return error_response(code="no_customer", detail="No subscription to manage.", http_status=400)
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        session = stripe.billing_portal.Session.create(
            customer=team.stripe_customer_id, return_url=f"{base}/teams/{team.id}"
        )
        return Response({"url": session.url})


class WebhookView(APIView):
    """Stripe webhook: signature-verified, keeps team subscription state in sync."""

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
        team = self._resolve_team(obj)
        if team is None:
            return Response(status=status.HTTP_200_OK)

        if etype == "checkout.session.completed":
            sub_id = obj.get("subscription")
            if obj.get("customer"):
                team.stripe_customer_id = obj["customer"]
                team.save(update_fields=["stripe_customer_id"])
            if sub_id:
                _sync_subscription(team, stripe.Subscription.retrieve(sub_id))
        elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
            _sync_subscription(team, obj)
        logger.info("stripe_webhook", extra={"type": etype, "team_id": team.id})
        return Response(status=status.HTTP_200_OK)

    def _resolve_team(self, obj):
        team_id = (obj.get("metadata") or {}).get("team_id") or obj.get("client_reference_id")
        if team_id:
            return Team.objects.filter(pk=team_id).first()
        customer = obj.get("customer")
        if customer:
            return Team.objects.filter(stripe_customer_id=customer).first()
        return None
