from django.contrib import admin

from docintel.apps.core.admin import UnscopedModelAdmin
from docintel.apps.sync.models import SyncEvent, SyncRule
from docintel.apps.sync.services import replay_event


@admin.register(SyncRule)
class SyncRuleAdmin(UnscopedModelAdmin):
    list_display = ("company", "event_type", "destination_url", "is_active")


@admin.action(description="Replay selected dead-lettered events")
def replay_selected(modeladmin, request, queryset):  # type: ignore[no-untyped-def]
    del modeladmin, request
    for event in queryset:
        replay_event(company=event.company, event_id=event.id)


@admin.register(SyncEvent)
class SyncEventAdmin(UnscopedModelAdmin):
    list_display = ("company", "event_type", "status", "attempts", "idempotency_key")
    list_filter = ("status", "event_type")
    actions = [replay_selected]
