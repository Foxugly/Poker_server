from rest_framework import serializers


class CreateRoomSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    username = serializers.CharField(max_length=50)


class JoinRoomSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50)
