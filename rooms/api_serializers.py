from rest_framework import serializers


class CreateRoomSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    # Anonymous rooms: username required. Team rooms: derived from the authed user.
    username = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    team = serializers.IntegerField(required=False, allow_null=True)


class JoinRoomSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
