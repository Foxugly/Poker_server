from django.urls import path

from .api_views import CheckoutView, PortalView, WebhookView

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="billing-checkout"),
    path("portal/", PortalView.as_view(), name="billing-portal"),
    path("webhook/", WebhookView.as_view(), name="billing-webhook"),
]
