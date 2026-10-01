"""Two approvals of the same version produce one outbox row."""

from __future__ import annotations

from threading import Barrier, Thread

import pytest
from django.db import close_old_connections

from docintel.apps.core.exceptions import PreconditionFailed
from docintel.apps.documents.review import approve_document
from docintel.apps.sync.models import SyncEvent
from docintel.tests.factories import DocumentFactory, MembershipFactory, UserFactory


@pytest.mark.django_db(transaction=True)
def test_concurrent_approvals_emit_one_event() -> None:
    membership = MembershipFactory(role="reviewer")
    document = DocumentFactory(
        company=membership.company,
        uploaded_by=membership.user,
        status="extracted",
        version=3,
    )
    other = UserFactory()
    MembershipFactory(company=membership.company, user=other, role="admin")
    barrier = Barrier(2)
    outcomes: list[str] = []

    def attempt(user) -> None:  # type: ignore[no-untyped-def]
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            approve_document(
                company=membership.company,
                user=user,
                document_id=document.id,
                expected_version=3,
            )
            outcomes.append("ok")
        except PreconditionFailed:
            outcomes.append("conflict")
        finally:
            close_old_connections()

    threads = [Thread(target=attempt, args=(membership.user,)), Thread(target=attempt, args=(other,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1
    assert SyncEvent.unscoped.filter(idempotency_key=f"document.approved:{document.id}:4").count() == 1
