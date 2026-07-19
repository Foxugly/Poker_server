from django.urls import path

from .api_views import FreeCatalogueView


urlpatterns = [
    path("catalogue/", FreeCatalogueView.as_view(), name="deck-catalogue"),
]
