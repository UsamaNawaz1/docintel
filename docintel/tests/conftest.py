"""Shared fixtures. Authentication always carries a company claim."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from docintel.apps.core.authentication import CompanyRefreshToken
from docintel.apps.core.models import Company, Membership, User
from docintel.tests.factories import CompanyFactory, MembershipFactory, UserFactory


@pytest.fixture
def company(db: None) -> Company:
    del db
    return CompanyFactory()


@pytest.fixture
def other_company(db: None) -> Company:
    del db
    return CompanyFactory()


@pytest.fixture
def user_factory(db: None) -> Callable[..., User]:
    del db

    def build(*, company: Company, role: str) -> User:
        user = UserFactory()
        MembershipFactory(company=company, user=user, role=role)
        return user

    return build


@pytest.fixture
def api_client() -> Callable[[User, Company], APIClient]:
    def build(user: User, company: Company) -> APIClient:
        client = APIClient()
        token = CompanyRefreshToken.for_user_and_company(user, company)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token!s}")
        return client

    return build


@pytest.fixture
def member_client(
    company: Company,
    user_factory: Callable[..., User],
    api_client: Callable[[User, Company], APIClient],
) -> APIClient:
    return api_client(user_factory(company=company, role=Membership.Role.MEMBER), company)
