from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB

from .models import ChronicleEvent

EVENT_PAYLOAD_KEYS = {
    "boon.offered": {"boon_type"},
    "boon.accepted": {"boon_type"},
    "boon.declined": {"boon_type"},
    "boon.called_in": {"boon_type"},
    "boon.fulfilled": {"boon_type"},
    "boon.canceled": {"boon_type"},
    "boon.disputed": {"boon_type"},
    "boon.upheld": {"boon_type"},
    "boon.acknowledged": {"boon_type"},
    "status.changed": {"old_value", "new_value"},
    "position.assigned": {"position"},
    "position.removed": {"position"},
    "status.request_approved": {"position", "old_value", "new_value"},
    "job.created": {"job_state", "job_priority"},
    "job.claimed": {"job_state", "job_priority"},
    "job.completed": {"job_state", "job_priority"},
    "job.reopened": {"job_state", "job_priority"},
    "bbs.posted": {"board", "post_title"},
    "builder.promoted": {"project_name"},
    "scene.curated": set(),
}


def _safe_payload(kind, payload):
    if not isinstance(payload, dict):
        raise TypeError("Chronicle event payload must be a dictionary.")
    allowed = EVENT_PAYLOAD_KEYS.get(kind)
    if allowed is None:
        raise ValueError(f"Unsupported Chronicle event kind: {kind}")
    unexpected = payload.keys() - allowed
    if unexpected:
        raise ValueError(f"Unsupported payload fields for {kind}: {', '.join(sorted(unexpected))}")
    return dict(payload)


def record_event(
    *,
    idempotency_key,
    source_app,
    source_type,
    source_id,
    kind,
    title,
    summary,
    payload,
    visibility,
    actor=None,
    participants=(),
    occurred_at=None,
    ai_generated=False,
    source_events=(),
):
    """Insert one unpublished event after its authoritative source transition commits."""
    if visibility not in ChronicleEvent.Visibility.values:
        raise ValueError(f"Unsupported Chronicle visibility: {visibility}")
    safe_payload = _safe_payload(kind, payload)
    participant_ids = tuple(participant.pk for participant in participants)
    source_event_ids = tuple(source.pk for source in source_events)
    actor_id = actor.pk if actor else None
    values = {
        "source_app": source_app,
        "source_type": source_type,
        "source_id": str(source_id),
        "kind": kind,
        "title": str(title)[:200],
        "summary": str(summary),
        "payload": safe_payload,
        "visibility": visibility,
        "actor_id": actor_id,
        "occurred_at": occurred_at or timezone.now(),
        "ai_generated": ai_generated,
    }

    def insert_event():
        event, _created = ChronicleEvent.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults=values,
        )
        if participant_ids:
            event.participants.add(*ObjectDB.objects.filter(pk__in=participant_ids))
        if source_event_ids:
            event.source_events.add(*ChronicleEvent.objects.filter(pk__in=source_event_ids))

    transaction.on_commit(insert_event)
    return idempotency_key


def public_events():
    return ChronicleEvent.objects.filter(
        visibility=ChronicleEvent.Visibility.PUBLIC,
        status=ChronicleEvent.Status.PUBLISHED,
    )


def participant_events(account):
    if not getattr(account, "is_authenticated", False):
        return ChronicleEvent.objects.none()
    return ChronicleEvent.objects.filter(
        visibility=ChronicleEvent.Visibility.PARTICIPANTS,
        status=ChronicleEvent.Status.PUBLISHED,
        participants__db_account=account,
    ).distinct()


def staff_events(user):
    if not getattr(user, "is_authenticated", False) or not (user.is_staff or user.is_superuser):
        return ChronicleEvent.objects.none()
    return ChronicleEvent.objects.all()


def _require_staff(user):
    if not getattr(user, "is_authenticated", False) or not (user.is_staff or user.is_superuser):
        raise PermissionError("Staff permission is required to moderate Chronicle events.")


@transaction.atomic
def publish_event(event_id, staff_user):
    _require_staff(staff_user)
    event = ChronicleEvent.objects.select_for_update().get(pk=event_id)
    if event.status != ChronicleEvent.Status.DRAFT:
        raise ValueError("Only draft Chronicle events can be published.")
    if event.supersedes_id:
        original = ChronicleEvent.objects.select_for_update().get(pk=event.supersedes_id)
        if original.status != ChronicleEvent.Status.PUBLISHED:
            raise ValueError("A correction can only replace a published Chronicle event.")
        original.status = ChronicleEvent.Status.SUPERSEDED
        original.save(update_fields=["status"])
    event.status = ChronicleEvent.Status.PUBLISHED
    event.published_by = staff_user
    event.published_at = timezone.now()
    event.save(update_fields=["status", "published_by", "published_at"])
    return event


@transaction.atomic
def correct_event(event_id, staff_user, *, title, summary, payload):
    _require_staff(staff_user)
    original = ChronicleEvent.objects.select_for_update().get(pk=event_id)
    if original.status != ChronicleEvent.Status.PUBLISHED:
        raise ValueError("Only published Chronicle events can be corrected.")
    corrected = ChronicleEvent.objects.create(
        idempotency_key=f"correction:{original.pk}:{uuid4()}",
        source_app=original.source_app,
        source_type=original.source_type,
        source_id=original.source_id,
        kind=original.kind,
        actor=staff_user,
        visibility=original.visibility,
        status=ChronicleEvent.Status.DRAFT,
        title=str(title)[:200],
        summary=str(summary),
        payload=_safe_payload(original.kind, payload),
        occurred_at=original.occurred_at,
        supersedes=original,
        ai_generated=original.ai_generated,
    )
    corrected.participants.set(original.participants.all())
    corrected.source_events.set(original.source_events.all())
    return corrected


@transaction.atomic
def redact_event(event_id, staff_user):
    _require_staff(staff_user)
    event = ChronicleEvent.objects.select_for_update().get(pk=event_id)
    if event.status == ChronicleEvent.Status.REDACTED:
        return event
    event.status = ChronicleEvent.Status.REDACTED
    event.title = ""
    event.summary = ""
    event.payload = {}
    event.redacted_by = staff_user
    event.redacted_at = timezone.now()
    event.save(update_fields=["status", "title", "summary", "payload", "redacted_by", "redacted_at"])
    return event


def characters_for_account(account):
    if not getattr(account, "is_authenticated", False):
        return ObjectDB.objects.none()
    return ObjectDB.objects.filter(db_account=account, db_typeclass_path="typeclasses.characters.Character")


def character_owned_by(account, character_id):
    if not getattr(account, "is_authenticated", False):
        return None
    return characters_for_account(account).filter(pk=character_id).first()
