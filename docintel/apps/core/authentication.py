"""JWT authentication that pins every request to one company.

The access token carries ``company_id``. We re-check ``Membership`` on each
request so a removed member loses access immediately, even if the token has
not expired yet. Missing membership is an authentication failure, not a 404,
because the caller has not established a tenant at all.
"""

from __future__ import annotations

import structlog
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from docintel.apps.core.models import Company, Membership, User

logger = structlog.get_logger(__name__)


class CompanyRefreshToken(RefreshToken):
    @classmethod
    def for_user_and_company(cls, user: User, company: Company) -> CompanyRefreshToken:
        token = cls.for_user(user)
        token["company_id"] = str(company.id)
        return token


class CompanyJWTAuthentication(JWTAuthentication):
    def authenticate(self, request: Request) -> tuple[User, CompanyRefreshToken] | None:
        header = self.get_header(request)
        if header is None:
            return None
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None
        validated = self.get_validated_token(raw_token)
        user = self.get_user(validated)
        if not isinstance(user, User):
            raise AuthenticationFailed("Invalid user.")
        company_id = validated.get("company_id")
        if not company_id:
            raise AuthenticationFailed("Token is missing company_id.")
        try:
            membership = Membership.unscoped.select_related("company").get(
                user=user,
                company_id=company_id,
            )
        except Membership.DoesNotExist as exc:
            raise AuthenticationFailed("Not a member of this company.") from exc
        request.company = membership.company  # type: ignore[attr-defined]
        request.membership = membership  # type: ignore[attr-defined]
        django_request = request._request
        django_request.company = membership.company  # type: ignore[attr-defined]
        django_request.membership = membership  # type: ignore[attr-defined]
        structlog.contextvars.bind_contextvars(company_id=str(membership.company_id))
        try:
            import sentry_sdk

            sentry_sdk.set_tag("tenant", str(membership.company_id))
        except ImportError:
            logger.debug("sentry_sdk_missing")
        return user, validated  # type: ignore[return-value]
