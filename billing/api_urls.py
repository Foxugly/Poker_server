from django.urls import path

from .api_views import BillingHistoryView, CheckoutView, PortalView, SubscriptionView, WebhookView

urlpatterns = [
    path("subscription/", SubscriptionView.as_view(), name="billing-subscription"),
    path("history/", BillingHistoryView.as_view(), name="billing-history"),
    path("checkout/", CheckoutView.as_view(), name="billing-checkout"),
    path("portal/", PortalView.as_view(), name="billing-portal"),
    path("webhook/", WebhookView.as_view(), name="billing-webhook"),
]
