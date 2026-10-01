"""Factories for every persistent model the tests touch."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from docintel.apps.core.models import Company, Membership, ToolPermission, User
from docintel.apps.documents.models import Document, Vendor
from docintel.apps.sync.models import SyncRule


class CompanyFactory(DjangoModelFactory):
    class Meta:
        model = Company

    name = factory.Sequence(lambda n: f"Company {n}")
    slug = factory.Sequence(lambda n: f"company-{n}")


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Sequence(lambda n: f"User {n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[no-untyped-def]
        password = kwargs.pop("password", "password-123")
        user = model_class(*args, **kwargs)
        user.set_password(password)
        user.save()
        return user


class MembershipFactory(DjangoModelFactory):
    class Meta:
        model = Membership

    company = factory.SubFactory(CompanyFactory)
    user = factory.SubFactory(UserFactory)
    role = Membership.Role.MEMBER


class ToolPermissionFactory(DjangoModelFactory):
    class Meta:
        model = ToolPermission

    company = factory.SubFactory(CompanyFactory)
    role = ""
    tool_slug = "documents"
    actions = factory.LazyFunction(lambda: ["view"])


class VendorFactory(DjangoModelFactory):
    class Meta:
        model = Vendor

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Vendor {n}")
    normalized_name = factory.LazyAttribute(lambda obj: obj.name.lower())
    tax_id = ""
    aliases = factory.LazyFunction(list)
    default_gl_code = "5000"


class DocumentFactory(DjangoModelFactory):
    class Meta:
        model = Document

    company = factory.SubFactory(CompanyFactory)
    uploaded_by = factory.SubFactory(UserFactory)
    s3_key = factory.LazyAttribute(
        lambda obj: f"tenants/{obj.company_id}/documents/2026/01/{obj.id}/file.pdf"
    )
    original_filename = "file.pdf"
    content_type = "application/pdf"
    size_bytes = 128
    status = Document.Status.UPLOADED
    sha256 = factory.Sequence(lambda n: f"{n:064x}")


class SyncRuleFactory(DjangoModelFactory):
    class Meta:
        model = SyncRule

    company = factory.SubFactory(CompanyFactory)
    event_type = "document.approved"
    destination_url = "https://example.com/hook"
    signing_secret = "secret"
    field_mapping = factory.LazyFunction(lambda: {"mappings": [{"source": "total", "target": "amount"}]})
    is_active = True
    timeout_seconds = 5
