"""Replay dead-lettered sync events without minting a new idempotency key."""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from docintel.apps.core.models import Company
from docintel.apps.sync.services import replay_event


class Command(BaseCommand):
    help = "Requeue a dead-lettered sync event. Safe to run more than once."

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument("--company", required=True, help="Company UUID")
        parser.add_argument("--event", required=True, help="SyncEvent UUID")

    def handle(self, *args: object, **options: object) -> None:
        del args
        try:
            company = Company.objects.get(id=UUID(str(options["company"])))
        except Company.DoesNotExist as exc:
            raise CommandError("Company not found.") from exc
        event = replay_event(company=company, event_id=UUID(str(options["event"])))
        self.stdout.write(f"{event.id} {event.status}")
