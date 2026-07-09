"""Account-level subscription (P2.7). A user subscribes to a plan that grants a quota
of teams (team1 → 1, team5 → 5). A team is "paid" when its owner has an active
subscription. Mirrors the Stripe subscription state via the webhook."""
from django.conf import settings
from django.db import models


class Subscription(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription")
    stripe_customer_id = models.CharField(max_length=64, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=32, blank=True, default="")  # Stripe status; "" = never subscribed
    plan = models.CharField(max_length=16, blank=True, default="")  # "team1" | "team5"
    interval = models.CharField(max_length=8, blank=True, default="")  # "monthly" | "yearly"
    current_period_end = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Subscription<{self.pk}> user={self.user_id} {self.plan}/{self.status}"
