"""HTTP boundary that creates/resolves a room before the WebSocket opens (contract §1).

HTTP creates/resolves the room and issues the ``participantToken`` + ``deckSnapshot``;
everything *inside* the room happens over the socket (contract §0.5).
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from decks.models import Deck, VoteType

from .api_serializers import CreateRoomSerializer, JoinRoomSerializer
from .codes import generate_token, generate_unique_code, normalize_code
from .models import Participant, Role, Room
from .snapshot import build_deck_snapshot

DELEGATION_POKER_CODE = "delegation_poker"


def _standard_deck():
    """The single standard Delegation Poker deck used by every free room (Phase 1)."""
    return (
        Deck.objects.filter(
            vote_type__code=DELEGATION_POKER_CODE, is_standard=True, is_active=True
        )
        .select_related("vote_type")
        .first()
    )


def _live_room_or_none(code):
    room = Room.objects.filter(code=normalize_code(code)).first()
    if room is None or not room.is_live:
        return None
    return room


class CreateRoomView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "create_room"

    @transaction.atomic
    def post(self, request):
        serializer = CreateRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        deck = _standard_deck()
        if deck is None:
            return Response(
                {"detail": "No standard deck configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        snapshot = build_deck_snapshot(deck)
        code = generate_unique_code(lambda c: Room.objects.filter(code=c).exists())
        room = Room(
            code=code,
            title=data["title"],
            vote_type=deck.vote_type,
            deck_snapshot=snapshot,
        )
        room.touch(save=False)
        room.save()

        facilitator = Participant.objects.create(
            room=room,
            token=generate_token(),
            display_name=data["username"],
            role=Role.FACILITATOR,
        )
        return Response(
            {
                "code": room.code,
                "roomTitle": room.title,
                "participantToken": facilitator.token,
                "role": Role.FACILITATOR,
                "deckSnapshot": snapshot,
            },
            status=status.HTTP_201_CREATED,
        )


class JoinRoomView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "join_room"

    @transaction.atomic
    def post(self, request, code):
        room = _live_room_or_none(code)
        if room is None:
            return Response({"detail": "Room not found or expired."}, status=status.HTTP_404_NOT_FOUND)

        serializer = JoinRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        participant = Participant.objects.create(
            room=room,
            token=generate_token(),
            display_name=serializer.validated_data["username"],
            role=Role.VOTER,
        )
        room.touch()
        return Response(
            {
                "code": room.code,
                "roomTitle": room.title,
                "participantToken": participant.token,
                "role": Role.VOTER,
                "deckSnapshot": room.deck_snapshot,
            },
            status=status.HTTP_200_OK,
        )


class RoomExistsView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "join_room"

    def get(self, request, code):
        room = _live_room_or_none(code)
        return Response(
            {
                "code": normalize_code(code),
                "roomTitle": room.title if room else "",
                "exists": room is not None,
            }
        )
