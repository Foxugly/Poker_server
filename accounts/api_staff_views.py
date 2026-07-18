"""Administration staff des comptes (spec lot A §A.4). Surface volontairement
minimale : rechercher un compte et basculer son accès offert. Toute autre
édition passe par l'admin Django."""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_serializers import StaffUserSerializer
from .models import BypassGrantLog, User

SEARCH_LIMIT = 50


class StaffUserListView(APIView):
    """GET ?q=<terme> — recherche par email ou display_name. Sans q, renvoie
    les comptes ayant un accès offert (la liste que le staff consulte en pratique)."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = User.objects.filter(Q(email__icontains=q) | Q(display_name__icontains=q))
        else:
            qs = User.objects.filter(subscription_bypass=True)
        qs = qs.order_by("email")[:SEARCH_LIMIT]
        return Response({"results": StaffUserSerializer(qs, many=True).data})


class StaffUserDetailView(APIView):
    """PATCH {subscription_bypass?, bypass_note?} — bascule l'accès offert."""

    permission_classes = [permissions.IsAdminUser]

    @transaction.atomic
    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        was_granted = user.subscription_bypass
        serializer = StaffUserSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Horodate à l'activation seulement : on garde la trace de l'octroi
        # initial même après une révocation.
        if user.subscription_bypass and not was_granted:
            user.bypass_granted_at = timezone.now()
            user.save(update_fields=["bypass_granted_at"])
        # Journal append-only : l'etat courant ne dit pas QUI a bascule le flag.
        # La bascule et l'écriture du journal partagent la même transaction
        # (@transaction.atomic) : si l'une échoue, l'autre est annulée avec elle.
        if user.subscription_bypass != was_granted:
            BypassGrantLog.objects.create(
                actor=request.user,
                actor_label=request.user.email,
                target=user,
                target_label=user.email,
                granted=user.subscription_bypass,
                note=user.bypass_note,
            )
        return Response(StaffUserSerializer(user).data)
