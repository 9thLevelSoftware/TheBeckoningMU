from functools import wraps
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone
from evennia.objects.models import ObjectDB

from .availability import available_events, event_available, event_projection, event_sources_available  # noqa: F401
from .models import ChronicleEvent

EVENT_PAYLOAD_KEYS = {
    "boon.offered": {"boon_type"},
    "boon.accepted": {"boon_type"},
    "boon.declined": {"boon_type"},
    "boon.called_in": {"boon_type"},
    "boon.fulfilled": {"boon_type"},
    "boon.canceled": {"boon_type"},
    "boon.disputed": {"boon_type"},
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
        with transaction.atomic():
            event, created = ChronicleEvent.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults=values,
            )
            if not created:
                return
            if participant_ids:
                event.participants.add(*ObjectDB.objects.filter(pk__in=participant_ids).values_list("pk", flat=True))
            if source_event_ids:
                event.source_events.add(
                    *ChronicleEvent.objects.filter(pk__in=source_event_ids).values_list("pk", flat=True)
                )

    transaction.on_commit(insert_event)
    return idempotency_key


def public_events():
    return available_events(audience="public")


def participant_events(account):
    if not getattr(account, "is_authenticated", False):
        return ChronicleEvent.objects.none()
    return available_events(audience="participants", account=account)


def staff_authorized(user):
    """Read current game authority without Evennia model/Attribute/tag caches."""
    if not getattr(user, "is_authenticated", False):
        return False
    accounts = get_user_model()
    authority = accounts.objects.filter(pk=user.pk, is_active=True).values("is_superuser").first()
    if authority is None:
        return False
    quell_values = accounts.db_attributes.through.objects.filter(
        accountdb_id=user.pk,
        attribute__db_model__iexact="accountdb",
        attribute__db_key__iexact="_quell",
        attribute__db_category__isnull=True,
        attribute__db_attrtype__isnull=True,
    ).values_list("attribute__db_value", flat=True)
    if authority["is_superuser"] and not any(bool(value) for value in quell_values):
        return True
    # Account.check_permstring disables only the superuser bypass when quelled;
    # explicit Builder or higher account permission tags remain authoritative.
    permissions = {
        str(value).lower()
        for value in accounts.db_tags.through.objects.filter(
            accountdb_id=user.pk,
            tag__db_model="accountdb",
            tag__db_tagtype="permission",
        ).values_list("tag__db_key", flat=True)
    }
    if "builder" in permissions:
        return True
    hierarchy = [str(value).lower() for value in settings.PERMISSION_HIERARCHY]
    return "builder" in hierarchy and bool(permissions.intersection(hierarchy[hierarchy.index("builder") + 1 :]))


def staff_events(user):
    if not staff_authorized(user):
        return ChronicleEvent.objects.none()
    return ChronicleEvent.objects.all()


def _require_staff(user):
    if not staff_authorized(user):
        raise PermissionError("Staff permission is required to moderate Chronicle events.")


class ModerationConflictError(ValueError):
    """A stale review or competing writer needs a fresh, explicit staff decision."""

    def __init__(self):
        super().__init__("This Chronicle entry changed. Reload Story Operations and review the current draft.")


def _database_conflict(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (IntegrityError, OperationalError) as error:
            raise ModerationConflictError() from error

    return guarded


def _require_version(value):
    if type(value) is not int or value < 1:
        raise ModerationConflictError()
    return value


def _reserve_original(event_id, expected_version=None, *, supersede=False):
    original = ChronicleEvent.objects.filter(pk=event_id, status=ChronicleEvent.Status.PUBLISHED)
    if expected_version is not None:
        original = original.filter(version=expected_version)
    changes = {"version": F("version")}
    if supersede:
        changes = {"status": ChronicleEvent.Status.SUPERSEDED, "version": F("version") + 1}
    if not original.update(**changes):
        ChronicleEvent.objects.get(pk=event_id)  # Preserve the normal not-found boundary.
        raise ModerationConflictError()


def _correction_changes(base, changes):
    if not isinstance(changes, dict) or changes.keys() - {"title", "summary", "payload"}:
        raise ValueError("Correction changes may contain only title, summary and payload.")
    title, summary = changes.get("title", base.title), changes.get("summary", base.summary)
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("A correction title must contain between 1 and 200 characters.")
    if not isinstance(summary, str):
        raise ValueError("A correction summary must be text.")
    return {
        "title": title.strip(),
        "summary": summary,
        "payload": _safe_payload(base.kind, changes.get("payload", base.payload)),
    }


def _copy_correction(original, base, actor, changes, *, revision_of=None, version=1):
    draft = ChronicleEvent.objects.create(
        idempotency_key=f"correction:{original.pk}:{uuid4()}",
        source_app=base.source_app,
        source_type=base.source_type,
        source_id=base.source_id,
        kind=base.kind,
        actor=actor,
        visibility=base.visibility,
        status=ChronicleEvent.Status.DRAFT,
        **_correction_changes(base, changes),
        occurred_at=base.occurred_at,
        supersedes=original,
        supersedes_version=original.version,
        revision_of=revision_of,
        version=version,
        ai_generated=base.ai_generated,
        lineage_status=base.lineage_status,
        lineage_note=base.lineage_note,
    )
    draft.participants.set(base.participants.all())
    draft.source_events.set(base.source_events.all())
    return draft


@_database_conflict
def begin_correction(event_id, actor, *, changes=None):
    """Begin once or resume the unchanged active draft; never overwrite a review."""
    _require_staff(actor)
    try:
        with transaction.atomic():
            # First write serializes SQLite writers too; no-op preserves the
            # published content/version while the draft decision is made.
            _reserve_original(event_id)
            _require_staff(actor)
            original = ChronicleEvent.objects.get(pk=event_id)
            existing = original.corrections.filter(status=ChronicleEvent.Status.DRAFT).first()
            if existing:
                return existing
            previous = original.corrections.order_by("-created_at", "-pk").first()
            return _copy_correction(
                original,
                original,
                actor,
                changes or {},
                revision_of=previous,
                version=previous.version + 1 if previous else 1,
            )
    except (IntegrityError, OperationalError) as error:
        try:
            existing = ChronicleEvent.objects.filter(
                supersedes_id=event_id,
                status=ChronicleEvent.Status.DRAFT,
                supersedes__status=ChronicleEvent.Status.PUBLISHED,
                supersedes_version=F("supersedes__version"),
            ).first()
        except (IntegrityError, OperationalError):
            existing = None
        if existing is not None:
            _require_staff(actor)
            return existing
        raise ModerationConflictError() from error


def correct_event(event_id, staff_user, *, title, summary, payload):
    """Compatibility for initial correction submissions; repeats resume unchanged."""
    return begin_correction(
        event_id, staff_user, changes={"title": str(title)[:200], "summary": str(summary), "payload": payload}
    )


@_database_conflict
def revise_correction(draft_id, actor, expected_version, changes):
    _require_staff(actor)
    _require_version(expected_version)
    snapshot = ChronicleEvent.objects.get(pk=draft_id)
    if not snapshot.supersedes_id or snapshot.supersedes_version is None:
        raise ModerationConflictError()
    values = _correction_changes(snapshot, changes)
    with transaction.atomic():
        _reserve_original(snapshot.supersedes_id, snapshot.supersedes_version)
        _require_staff(actor)
        changed = ChronicleEvent.objects.filter(
            pk=draft_id,
            status=ChronicleEvent.Status.DRAFT,
            version=expected_version,
            supersedes_id=snapshot.supersedes_id,
            supersedes_version=snapshot.supersedes_version,
        ).update(
            status=ChronicleEvent.Status.DISCARDED,
            version=F("version") + 1,
            discarded_by=actor,
            discarded_at=timezone.now(),
        )
        if not changed:
            raise ModerationConflictError()
        previous = ChronicleEvent.objects.get(pk=draft_id)
        original = ChronicleEvent.objects.get(pk=previous.supersedes_id)
        return _copy_correction(original, previous, actor, values, revision_of=previous, version=expected_version + 1)


@_database_conflict
def discard_correction(draft_id, actor, expected_version):
    _require_staff(actor)
    _require_version(expected_version)
    with transaction.atomic():
        changed = ChronicleEvent.objects.filter(
            pk=draft_id,
            status=ChronicleEvent.Status.DRAFT,
            version=expected_version,
            supersedes__isnull=False,
        ).update(
            status=ChronicleEvent.Status.DISCARDED,
            version=F("version") + 1,
            discarded_by=actor,
            discarded_at=timezone.now(),
        )
        if not changed:
            ChronicleEvent.objects.get(pk=draft_id)
            raise ModerationConflictError()
        _require_staff(actor)
        return ChronicleEvent.objects.get(pk=draft_id)


@_database_conflict
def publish_event(event_id, staff_user, expected_version=1):
    """Publish the reviewed version, replacing only its unchanged published source."""
    _require_staff(staff_user)
    _require_version(expected_version)
    snapshot = ChronicleEvent.objects.get(pk=event_id)
    with transaction.atomic():
        if snapshot.supersedes_id:
            if snapshot.supersedes_version is None:
                raise ModerationConflictError()
            _reserve_original(snapshot.supersedes_id, snapshot.supersedes_version, supersede=True)
        changed = ChronicleEvent.objects.filter(
            pk=event_id,
            status=ChronicleEvent.Status.DRAFT,
            version=expected_version,
        ).update(
            status=ChronicleEvent.Status.PUBLISHED,
            version=F("version") + 1,
            published_by=staff_user,
            published_at=timezone.now(),
        )
        if not changed:
            raise ModerationConflictError()
        _require_staff(staff_user)
        event = ChronicleEvent.objects.get(pk=event_id)
        if event.source_type == "ChronicleGenerationRequest":
            from .generation import validate_generated_publication

            validate_generated_publication(event)
        if not event_sources_available(
            event, audience="public" if event.visibility == "public" else "account", account=staff_user
        ):
            raise ValueError("This draft has unavailable sources; create a new valid draft for review.")
        if event.visibility == "public" and not event_available(event, "public"):
            raise ValueError("The draft has no current source provenance.")
        if event.supersedes_id:
            withdraw_dependents([event.supersedes_id], staff_user, "source_corrected", _exclude_ids={event.pk})
        return event


def withdraw_dependents(source_ids, actor, reason, *, _exclude_ids=()):
    """Withdraw the transitive source/copy graph without deleting retained prose."""
    _require_staff(actor)
    excluded = set(_exclude_ids)
    visited = {int(pk) for pk in source_ids} | excluded
    frontier = visited - excluded
    descendants = set()
    with transaction.atomic():
        while frontier:
            found = (
                set(
                    ChronicleEvent.objects.filter(
                        Q(source_events__pk__in=frontier)
                        | Q(supersedes_id__in=frontier)
                        | Q(revision_of_id__in=frontier)
                    ).values_list("pk", flat=True)
                )
                - visited
            )
            visited.update(found)
            descendants.update(found)
            frontier = found
        eligible = ChronicleEvent.objects.filter(pk__in=descendants, status__in=("published", "draft"))
        withdrawn = list(eligible.order_by("pk").values_list("pk", flat=True))
        eligible.update(
            status="withdrawn",
            version=F("version") + 1,
            withdrawn_by=actor,
            withdrawn_at=timezone.now(),
            withdrawal_reason=reason,
        )
    return {"withdrawn_ids": withdrawn}


@_database_conflict
def redact_event(event_id, staff_user, expected_version=None):
    _require_staff(staff_user)
    snapshot = ChronicleEvent.objects.get(pk=event_id)
    if snapshot.status == ChronicleEvent.Status.REDACTED:
        return snapshot
    version = snapshot.version if expected_version is None else _require_version(expected_version)
    with transaction.atomic():
        changed = ChronicleEvent.objects.filter(pk=event_id, version=version, status=snapshot.status).update(
            status=ChronicleEvent.Status.REDACTED,
            version=F("version") + 1,
            title="",
            summary="",
            payload={},
            redacted_by=staff_user,
            redacted_at=timezone.now(),
        )
        if not changed:
            raise ModerationConflictError()
        _require_staff(staff_user)
        # Corrections and replaced draft revisions contain copied target text.
        # Traverse that copy family separately from generic derivative recaps.
        family, frontier = {event_id}, {event_id}
        while frontier:
            relatives = set(
                ChronicleEvent.objects.filter(
                    Q(supersedes_id__in=frontier) | Q(revision_of_id__in=frontier)
                ).values_list("pk", flat=True)
            )
            relatives.update(
                ChronicleEvent.objects.filter(pk__in=frontier, revision_of__isnull=False).values_list(
                    "revision_of_id", flat=True
                )
            )
            frontier = relatives - family
            family.update(frontier)
        ChronicleEvent.objects.filter(pk__in=family - {event_id}).exclude(status="redacted").update(
            status="redacted",
            version=F("version") + 1,
            title="",
            summary="",
            payload={},
            redacted_by=staff_user,
            redacted_at=timezone.now(),
        )
        withdraw_dependents(family, staff_user, "source_redacted")
        return ChronicleEvent.objects.get(pk=event_id)


def characters_for_account(account):
    if not getattr(account, "is_authenticated", False):
        return ObjectDB.objects.none()
    return ObjectDB.objects.filter(vtm_bio__account=account, db_typeclass_path="typeclasses.characters.Character")


def character_owned_by(account, character_id):
    if not getattr(account, "is_authenticated", False):
        return None
    return characters_for_account(account).filter(pk=character_id).first()
