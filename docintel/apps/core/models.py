"""Tenancy and access-control models."""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.db import models

from docintel.apps.core.ids import uuid7
from docintel.apps.core.managers import TenantManager, UnscopedManager

TOOL_DOCUMENTS = "documents"
TOOL_IMPORTS = "imports"

ACTIONS = ("view", "create", "review", "export", "admin")

# Built-in grants used when a company has not stored a ToolPermission row.
# A row, when present, replaces the default for that user or role.
DEFAULT_ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(ACTIONS),
    "admin": frozenset(ACTIONS),
    "reviewer": frozenset({"view", "review"}),
    "member": frozenset({"view", "create"}),
}


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def create_user(
        self,
        email: str,
        password: str | None = None,
        *,
        name: str = "",
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> User:
        if not email:
            raise ValueError("email is required")
        user = self.model(
            email=self.normalize_email(email).lower(),
            name=name,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, *, name: str = "") -> User:
        return self.create_user(email, password, name=name, is_staff=True, is_superuser=True)


class User(AbstractBaseUser, PermissionsMixin):
    """Email is the login. Company membership lives on ``Membership``, not here."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        db_table = "core_user"

    def __str__(self) -> str:
        return self.email


class Company(models.Model):
    """A tenant. All business rows point here and are queried through it."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_company"
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return self.slug


class TenantScopedModel(models.Model):
    """Abstract base for rows that must never leak across companies.

    Concrete models that declare their own ``Meta`` must repeat
    ``base_manager_name`` and ``default_manager_name`` and set
    ``abstract = False``. Subclassing this ``Meta`` without clearing
    ``abstract`` would make the child abstract too.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        abstract = True
        base_manager_name = "unscoped"
        default_manager_name = "objects"


class Membership(TenantScopedModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        REVIEWER = "reviewer", "Reviewer"
        MEMBER = "member", "Member"

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "core_membership"
        constraints = [
            models.UniqueConstraint(fields=["company", "user"], name="membership_company_user"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role}"


class ToolPermission(TenantScopedModel):
    """Optional grant that replaces the role default for one tool.

    Exactly one of ``user`` or ``role`` is set. User grants win over role
    grants; role grants win over ``DEFAULT_ROLE_ACTIONS``.
    """

    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tool_permissions",
    )
    role = models.CharField(max_length=20, blank=True, choices=Membership.Role.choices)
    tool_slug = models.CharField(max_length=40)
    actions = ArrayField(models.CharField(max_length=20), default=list)

    class Meta:
        abstract = False
        base_manager_name = "unscoped"
        default_manager_name = "objects"
        db_table = "core_tool_permission"
        constraints = [
            models.CheckConstraint(
                name="toolperm_user_xor_role",
                condition=(
                    models.Q(user__isnull=False, role="") | models.Q(user__isnull=True) & ~models.Q(role="")
                ),
            ),
            models.UniqueConstraint(
                fields=["company", "user", "tool_slug"],
                condition=models.Q(user__isnull=False),
                name="toolperm_user_tool",
            ),
            models.UniqueConstraint(
                fields=["company", "role", "tool_slug"],
                condition=models.Q(user__isnull=True),
                name="toolperm_role_tool",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "tool_slug"], name="toolperm_company_tool"),
        ]
