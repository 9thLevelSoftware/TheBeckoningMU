"""Builder-authored curation; generated prose never proposes memory writes."""

from datetime import datetime
from functools import wraps

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone

from chronicle.services import event_available, staff_authorized
from traits.models import CharacterBio

from .models import MemoryFact, NarrativePersona

MAX_CURATED_TEXT = 4000
MEMORY_FIELDS = {"persona_id", "subject_id", "text", "source_event_id", "staff_entry", "visibility", "expires_at"}


class CurationConflictError(ValueError):
    def __init__(self):
        super().__init__("This narrative record changed. Reload the curation page and review the current version.")


class CurationValidationError(ValueError):
    pass


def _require_builder(actor):
    if not staff_authorized(actor):
        raise PermissionError("Current Builder permission is required for narrative curation.")


def _database_conflict(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (IntegrityError, OperationalError) as error:
            raise CurationConflictError() from error

    return guarded


def _version(value):
    if type(value) is not int or value < 1:
        raise CurationConflictError()
    return value


def _identifier(value, *, optional=False):
    if optional and value in (None, ""):
        return None
    if type(value) not in (int, str) or not str(value).isascii() or not str(value).isdigit() or int(value) <= 0:
        raise CurationValidationError("Choose a valid existing record.")
    return int(value)


def _text(value, label, *, optional=False):
    if not isinstance(value, str) or len(value) > MAX_CURATED_TEXT or (not optional and not value.strip()):
        raise CurationValidationError(
            f"{label} must contain {'0' if optional else '1'} to {MAX_CURATED_TEXT} characters."
        )
    return value.strip()


def _persona(persona_id):
    from .services import validate_persona_character

    try:
        persona = NarrativePersona.objects.get(pk=_identifier(persona_id))
        validate_persona_character(persona.character)
        return persona
    except (NarrativePersona.DoesNotExist, ValueError) as error:
        raise CurationValidationError("Choose a registered, persistent, account-less NPC persona.") from error


def _subject(subject_id):
    from .services import persisted_character_identity

    subject_id = _identifier(subject_id, optional=True)
    if subject_id is None:
        return None
    try:
        return persisted_character_identity(subject_id)["id"]
    except ValueError as error:
        raise CurationValidationError("A memory subject must be an existing Character.") from error


def memory_source_available(fact, actor):
    """Effective source eligibility for review queues; never changes stored audit."""
    if not fact.source_event_id:
        return True
    if fact.visibility == "staff":
        return event_available(fact.source_event_id, "staff", actor)
    if fact.visibility == "public":
        return event_available(fact.source_event_id, "public")
    bio = CharacterBio.objects.filter(character_id=fact.subject_id).select_related("account").first()
    owner = bio.account if bio else None
    return event_available(fact.source_event_id, "account", owner, character_id=fact.subject_id)


def _memory_values(values, actor):
    persona = _persona(values["persona_id"])
    subject_id = _subject(values.get("subject_id"))
    visibility = values.get("visibility")
    if visibility not in MemoryFact.Visibility.values:
        raise CurationValidationError("Choose public, private to subject, or staff-only scope.")
    if visibility == "private" and subject_id is None:
        raise CurationValidationError("Private memory facts require a Character subject.")
    text = _text(values.get("text"), "Memory text")
    staff_entry = _text(values.get("staff_entry", ""), "Staff provenance", optional=True)
    source_id = _identifier(values.get("source_event_id"), optional=True)
    if source_id is None and not staff_entry:
        raise CurationValidationError("Provide a source Chronicle entry or a staff provenance annotation.")
    expires = values.get("expires_at")
    if expires is not None and (
        not isinstance(expires, datetime) or timezone.is_naive(expires) or expires <= timezone.now()
    ):
        raise CurationValidationError("Expiry must be a future date and time, or blank.")
    result = {
        "persona_id": persona.pk,
        "subject_id": subject_id,
        "text": text,
        "source_event_id": source_id,
        "staff_entry": staff_entry,
        "visibility": visibility,
        "expires_at": expires,
    }
    if not memory_source_available(MemoryFact(**result), actor):
        raise CurationValidationError("The Chronicle source or its ancestry is unavailable for this memory's scope.")
    return result


@_database_conflict
def register_persona(character, actor, profile=""):
    from .services import validate_persona_character

    _require_builder(actor)
    validate_persona_character(character)
    profile = _text(profile, "Persona profile", optional=True)
    with transaction.atomic():
        _require_builder(actor)
        validate_persona_character(character)
        if NarrativePersona.objects.filter(character_id=character.pk).exists():
            raise CurationValidationError("This NPC already has a persona. Edit its existing profile.")
        return NarrativePersona.objects.create(
            character=character, profile=profile, registered_by=actor, updated_by=actor
        )


@_database_conflict
def update_persona(persona_id, actor, expected_version, profile):
    _require_builder(actor)
    _version(expected_version)
    profile = _text(profile, "Persona profile", optional=True)
    with transaction.atomic():
        if not NarrativePersona.objects.filter(pk=persona_id, version=expected_version).update(
            version=F("version") + 1, profile=profile, updated_by=actor, updated_at=timezone.now()
        ):
            raise CurationConflictError()
        _require_builder(actor)
        return _persona(persona_id)


@_database_conflict
def create_memory_fact(
    actor,
    *,
    persona_id,
    subject_id=None,
    text,
    source_event_id=None,
    staff_entry="",
    visibility="private",
    expires_at=None,
):
    _require_builder(actor)
    values = _memory_values(
        {
            "persona_id": persona_id,
            "subject_id": subject_id,
            "text": text,
            "source_event_id": source_event_id,
            "staff_entry": staff_entry,
            "visibility": visibility,
            "expires_at": expires_at,
        },
        actor,
    )
    with transaction.atomic():
        _require_builder(actor)
        values = _memory_values(values, actor)
        return MemoryFact.objects.create(**values, created_by=actor, updated_by=actor, updated_at=timezone.now())


@_database_conflict
def revise_memory_fact(fact_id, actor, expected_version, changes):
    _require_builder(actor)
    _version(expected_version)
    if not isinstance(changes, dict) or changes.keys() - MEMORY_FIELDS:
        raise CurationValidationError(
            "Revision changes may contain only memory text, scope, expiry and provenance fields."
        )
    snapshot = MemoryFact.objects.get(pk=fact_id)
    values = {key: getattr(snapshot, key) for key in MEMORY_FIELDS}
    values.update(changes)
    values = _memory_values(values, actor)
    root_id = snapshot.revision_root_id or snapshot.pk
    with transaction.atomic():
        if not MemoryFact.objects.filter(pk=fact_id, version=expected_version, status__in=("draft", "approved")).update(
            status="withdrawn",
            version=F("version") + 1,
            withdrawn_by=actor,
            withdrawn_at=timezone.now(),
            withdrawal_reason="replaced_for_review",
            updated_by=actor,
            updated_at=timezone.now(),
        ):
            raise CurationConflictError()
        _require_builder(actor)
        if MemoryFact.objects.filter(pk=root_id, status="redacted").exists():
            raise CurationConflictError()
        values = _memory_values(values, actor)
        return MemoryFact.objects.create(
            **values,
            revision_of_id=fact_id,
            revision_root_id=root_id,
            version=expected_version + 1,
            created_by=actor,
            updated_by=actor,
            updated_at=timezone.now(),
        )


@_database_conflict
def approve_memory_fact(fact_id, actor, expected_version):
    _require_builder(actor)
    _version(expected_version)
    with transaction.atomic():
        if not MemoryFact.objects.filter(pk=fact_id, status="draft", version=expected_version).update(
            status="approved",
            version=F("version") + 1,
            approved_by=actor,
            approved_at=timezone.now(),
            updated_by=actor,
            updated_at=timezone.now(),
        ):
            raise CurationConflictError()
        _require_builder(actor)
        fact = MemoryFact.objects.get(pk=fact_id)
        if fact.revision_root_id and MemoryFact.objects.filter(pk=fact.revision_root_id, status="redacted").exists():
            raise CurationConflictError()
        _memory_values({key: getattr(fact, key) for key in MEMORY_FIELDS}, actor)
        return fact


@_database_conflict
def redact_memory_fact(fact_id, actor, expected_version):
    _require_builder(actor)
    _version(expected_version)
    snapshot = MemoryFact.objects.get(pk=fact_id)
    if snapshot.status == "redacted":
        return snapshot
    root_id = snapshot.revision_root_id or snapshot.pk
    with transaction.atomic():
        if not MemoryFact.objects.filter(pk=fact_id, version=expected_version, status=snapshot.status).update(
            status="redacted",
            version=F("version") + 1,
            text="",
            staff_entry="",
            redacted_by=actor,
            redacted_at=timezone.now(),
            updated_by=actor,
            updated_at=timezone.now(),
        ):
            raise CurationConflictError()
        _require_builder(actor)
        MemoryFact.objects.filter(Q(pk=root_id) | Q(revision_root_id=root_id)).exclude(pk=fact_id).exclude(
            status="redacted"
        ).update(
            status="redacted",
            version=F("version") + 1,
            text="",
            staff_entry="",
            redacted_by=actor,
            redacted_at=timezone.now(),
            updated_by=actor,
            updated_at=timezone.now(),
        )
        return MemoryFact.objects.get(pk=fact_id)
