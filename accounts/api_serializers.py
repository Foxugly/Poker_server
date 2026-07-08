from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    # No validators on email so DRF's auto UniqueValidator doesn't fire — a
    # duplicate must not 400 (enumeration leak); the view handles it anti-leak.
    email = serializers.EmailField(validators=[])
    password = serializers.CharField(write_only=True, min_length=8)
    display_name = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    turnstile_token = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["email", "password", "display_name", "turnstile_token"]

    def validate_email(self, value):
        return value.strip().lower()

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"], password=validated_data["password"]
        )
        display_name = (validated_data.get("display_name") or "").strip()
        if display_name:
            user.display_name = display_name
            user.save(update_fields=["display_name"])
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            email=attrs["email"].strip().lower(),
            password=attrs["password"],
        )
        if not user or not user.is_active:
            raise serializers.ValidationError("Invalid credentials.")
        attrs["user"] = user
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    turnstile_token = serializers.CharField(write_only=True, required=False, allow_blank=True)


class ResetPasswordConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=8)


class EmailConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()


class EmailResendSerializer(serializers.Serializer):
    email = serializers.EmailField()


class MagicLinkRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    turnstile_token = serializers.CharField(write_only=True, required=False, allow_blank=True)


class MagicLinkVerifySerializer(serializers.Serializer):
    token = serializers.CharField()


class UserMeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # is_staff/is_superuser read-only so the SPA can gate an admin link client-side.
        fields = ["id", "email", "display_name", "is_active", "email_confirmed", "is_staff", "is_superuser"]
        read_only_fields = ["id", "email", "is_active", "email_confirmed", "is_staff", "is_superuser"]


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["display_name"]


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserMeSerializer()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True, help_text="Refresh token to invalidate")


def build_token_response_for_user(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": UserMeSerializer(user).data,
    }
