"""Every allowed edge succeeds and a sample of forbidden edges raise."""

from __future__ import annotations

import pytest

from docintel.apps.core.exceptions import InvalidTransition
from docintel.apps.documents.models import Document
from docintel.tests.factories import DocumentFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "target"),
    [
        (Document.Status.PENDING_UPLOAD, Document.Status.UPLOADED),
        (Document.Status.UPLOADED, Document.Status.PROCESSING),
        (Document.Status.PROCESSING, Document.Status.NEEDS_REVIEW),
        (Document.Status.PROCESSING, Document.Status.EXTRACTED),
        (Document.Status.PROCESSING, Document.Status.FAILED),
        (Document.Status.NEEDS_REVIEW, Document.Status.APPROVED),
        (Document.Status.NEEDS_REVIEW, Document.Status.REJECTED),
        (Document.Status.EXTRACTED, Document.Status.APPROVED),
        (Document.Status.FAILED, Document.Status.PROCESSING),
        (Document.Status.REJECTED, Document.Status.PROCESSING),
    ],
)
def test_allowed_transitions(start: str, target: str) -> None:
    document = DocumentFactory(status=start, version=1)
    document.transition_to(target)
    assert document.status == target
    assert document.version == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "target"),
    [
        (Document.Status.PENDING_UPLOAD, Document.Status.APPROVED),
        (Document.Status.APPROVED, Document.Status.PROCESSING),
        (Document.Status.EXTRACTED, Document.Status.UPLOADED),
        (Document.Status.FAILED, Document.Status.APPROVED),
        (Document.Status.NEEDS_REVIEW, Document.Status.UPLOADED),
    ],
)
def test_forbidden_transitions(start: str, target: str) -> None:
    document = DocumentFactory(status=start)
    with pytest.raises(InvalidTransition):
        document.transition_to(target)
