from rest_framework import serializers


class CreateRoomSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    # Anonymous rooms: username required. Team rooms: derived from the authed user.
    username = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    team = serializers.IntegerField(required=False, allow_null=True)
    # Account-less rooms choose here, at creation: with no Team to persist the
    # choice, it only ever lives in the room's frozen snapshots. Ignored for team
    # rooms, which take the team's enabled decks.
    deck_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    card_back_id = serializers.IntegerField(required=False, allow_null=True)


class JoinRoomSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
