from django.urls import path

from .api_views import CardBackUploadView, FeltUploadView, FreeCatalogueView


urlpatterns = [
    path("catalogue/", FreeCatalogueView.as_view(), name="deck-catalogue"),
    path("card-backs/", CardBackUploadView.as_view(), name="card-back-upload"),
    path("card-backs/<int:pk>/", CardBackUploadView.as_view(), name="card-back-detail"),
    path("felts/", FeltUploadView.as_view(), name="felt-upload"),
    path("felts/<int:pk>/", FeltUploadView.as_view(), name="felt-detail"),
]
