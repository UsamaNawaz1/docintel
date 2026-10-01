"""Login issues a refresh/access pair bound to a single company."""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from docintel.apps.core.authentication import CompanyRefreshToken
from docintel.apps.core.models import Membership, User


class TokenObtainSerializer(serializers.Serializer[dict[str, object]]):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    company_id = serializers.UUIDField()


class TokenObtainView(APIView):
    authentication_classes: list[object] = []
    permission_classes: list[object] = []

    def post(self, request: Request) -> Response:
        serializer = TokenObtainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = str(serializer.validated_data["email"]).lower()
        password = str(serializer.validated_data["password"])
        company_id = serializer.validated_data["company_id"]
        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return _unauthorized()
        if not user.check_password(password):
            return _unauthorized()
        try:
            membership = Membership.unscoped.select_related("company").get(
                user=user,
                company_id=company_id,
            )
        except Membership.DoesNotExist:
            return _unauthorized()
        refresh = CompanyRefreshToken.for_user_and_company(user, membership.company)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "company_id": str(membership.company_id),
            }
        )


class CompanyTokenRefreshView(TokenRefreshView):
    authentication_classes: list[object] = []
    permission_classes: list[object] = []


def _unauthorized() -> Response:
    return Response(
        {
            "error": {
                "code": "authentication_failed",
                "message": "Invalid credentials.",
                "details": {},
            }
        },
        status=status.HTTP_401_UNAUTHORIZED,
    )
