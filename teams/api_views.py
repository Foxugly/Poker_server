import re

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api_errors import error_response

from billing.service import paid_required

from .invitations import send_invitation_email
from .models import Invitation, Team, TeamMembership, TeamRole
from .permissions import is_admin, is_member, is_owner, membership_of
from .serializers import (
    AcceptInviteSerializer,
    InvitationSerializer,
    InviteCreateSerializer,
    MembershipSerializer,
    RoleUpdateSerializer,
    TeamCreateSerializer,
    TeamSerializer,
)

INVITE_TTL_DAYS = 7
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class TeamListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        teams = (
            Team.objects.filter(memberships__user=request.user)
            .select_related("owner")
            .prefetch_related("memberships")
            .distinct()
        )
        return Response(TeamSerializer(teams, many=True, context={"request": request}).data)

    @transaction.atomic
    def post(self, request):
        serializer = TeamCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = Team.objects.create(name=serializer.validated_data["name"].strip(), owner=request.user)
        TeamMembership.objects.create(team=team, user=request.user, role=TeamRole.OWNER)
        return Response(TeamSerializer(team, context={"request": request}).data, status=status.HTTP_201_CREATED)


class TeamDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _team(self, team_id):
        return get_object_or_404(Team.objects.prefetch_related("memberships"), pk=team_id)

    def get(self, request, team_id):
        team = self._team(team_id)
        if not is_member(team, request.user):
            return error_response(code="not_a_member", detail="Not a member of this team.", http_status=403)
        return Response(TeamSerializer(team, context={"request": request}).data)

    def patch(self, request, team_id):
        team = self._team(team_id)
        if not is_admin(team, request.user):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)
        updates = []
        name = (request.data.get("name") or "").strip()
        if name:
            team.name = name
            updates.append("name")
        # Appearance (P2.6): card-back + felt colours, validated as #RRGGBB[AA].
        # Appearance is a paid feature (P2.7): gated once billing is live.
        if ("card_back_color" in request.data or "felt_color" in request.data):
            if (err := paid_required(team)) is not None:
                return err
        for field in ("card_back_color", "felt_color"):
            if field in request.data:
                color = (request.data.get(field) or "").strip()
                if not _HEX_COLOR.match(color):
                    return error_response(code="invalid_color", detail="Expected #RRGGBB.", http_status=400)
                setattr(team, field, color)
                updates.append(field)
        if updates:
            team.save(update_fields=updates)
        return Response(TeamSerializer(team, context={"request": request}).data)

    def delete(self, request, team_id):
        team = self._team(team_id)
        if not is_owner(team, request.user):
            return error_response(code="forbidden", detail="Only the owner can delete the team.", http_status=403)
        team.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, team_id):
        team = get_object_or_404(Team, pk=team_id)
        if not is_member(team, request.user):
            return error_response(code="not_a_member", detail="Not a member of this team.", http_status=403)
        members = team.memberships.select_related("user").order_by("joined_at")
        return Response(MembershipSerializer(members, many=True).data)


class MemberDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, team_id, user_id):
        team = get_object_or_404(Team, pk=team_id)
        if not is_admin(team, request.user):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)
        membership = get_object_or_404(TeamMembership, team=team, user_id=user_id)
        if membership.role == TeamRole.OWNER:
            return error_response(code="cannot_change_owner", detail="The owner's role can't be changed here.", http_status=400)
        serializer = RoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership.role = serializer.validated_data["role"]
        membership.save(update_fields=["role"])
        return Response(MembershipSerializer(membership).data)

    def delete(self, request, team_id, user_id):
        team = get_object_or_404(Team, pk=team_id)
        membership = get_object_or_404(TeamMembership, team=team, user_id=user_id)
        is_self = str(request.user.id) == str(user_id)
        if not (is_self or is_admin(team, request.user)):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)
        if membership.role == TeamRole.OWNER:
            return error_response(code="cannot_remove_owner", detail="The owner can't leave; transfer ownership first.", http_status=400)
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, team_id):
        team = get_object_or_404(Team, pk=team_id)
        if not is_admin(team, request.user):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)
        pending = team.invitations.filter(accepted_at__isnull=True, expires_at__gt=timezone.now())
        return Response(InvitationSerializer(pending, many=True).data)

    def post(self, request, team_id):
        team = get_object_or_404(Team, pk=team_id)
        if not is_admin(team, request.user):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)
        serializer = InviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        if team.memberships.filter(user__email__iexact=email).exists():
            return error_response(code="already_member", detail="That person is already a member.", http_status=400)
        invitation = Invitation.objects.create(
            team=team,
            email=email,
            role=serializer.validated_data["role"],
            invited_by=request.user,
            expires_at=timezone.now() + timezone.timedelta(days=INVITE_TTL_DAYS),
        )
        send_invitation_email(invitation)
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class InvitationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, team_id, inv_id):
        team = get_object_or_404(Team, pk=team_id)
        if not is_admin(team, request.user):
            return error_response(code="forbidden", detail="Admin role required.", http_status=403)
        get_object_or_404(Invitation, team=team, pk=inv_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AcceptInvitationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = AcceptInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = Invitation.objects.select_related("team").filter(token=serializer.validated_data["token"]).first()
        if invitation is None or not invitation.is_pending:
            return error_response(code="invite_invalid", detail="This invitation is invalid, expired, or already used.", http_status=400)
        # The signed-in user must match the invited email (a leaked token can't be reused by anyone).
        if request.user.email.lower() != invitation.email.lower():
            return error_response(code="invite_email_mismatch",
                                  detail="Sign in with the email this invitation was sent to.", http_status=403)
        TeamMembership.objects.get_or_create(
            team=invitation.team, user=request.user, defaults={"role": invitation.role}
        )
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])
        return Response(TeamSerializer(invitation.team, context={"request": request}).data, status=status.HTTP_200_OK)
