"""Public deck catalogue for account-less rooms.

An anonymous room has no Team to hold its choices, so it picks at creation time
and the choice is frozen in the room's snapshots. This endpoint is what the
create-room screen reads to offer that choice.
"""
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .selection import available_card_backs, available_decks
from .serializers import CardBackSerializer, DeckSerializer


class FreeCatalogueView(APIView):
    """The decks and card backs offered to a room without an account."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        decks = available_decks(None).prefetch_related("cards", "translations")
        backs = available_card_backs(None)
        return Response(
            {
                "decks": DeckSerializer(decks, many=True).data,
                "card_backs": CardBackSerializer(backs, many=True).data,
            }
        )
