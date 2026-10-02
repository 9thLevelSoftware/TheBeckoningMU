"""
Web chargen units of work: create, approve, reject, revoke and resubmit.

Each unit is one callable that runs entirely on the reactor thread (the views
hand it over with web.main_thread.call_in_main_thread) and does all of its own
writes there. The web thread only parses, validates and reads before the
hand-off, and never opens a transaction around it.

A unit checks everything it can before it changes anything. If something
still fails after it started changing the world, it undoes its own work with
Evennia-level operations (removing the character from the account's list,
deleting the objects and rows it created, restoring the sheet), never with a
DB rollback: idmapper instances, contents caches and account.characters
would survive a rollback.
"""

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from evennia.utils import logger

from traits.models import CharacterBio
from world.rules_chargen import apply_chargen

APPROVAL_BUCKET = "Approval"


class ChargenError(Exception):
    """A refusal to show the player. `status` is the HTTP status to answer with."""

    def __init__(self, errors, status=400):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        self.status = status
        super().__init__("; ".join(self.errors))


def character_class():
    from typeclasses.characters import Character

    return Character


def name_taken(name, exclude_id=None):
    """True if any character already has this name (case-insensitive)."""
    matches = character_class().objects.filter_family(db_key__iexact=name)
    if exclude_id:
        matches = matches.exclude(id=exclude_id)
    return matches.exists()


def active_application_count(account):
    """Pending and approved characters owned by `account`."""
    return CharacterBio.objects.filter(account=account, status__in=("submitted", "approved")).count()


def notify_account(account, message, notification_type="info"):
    """Store a notification for the account's next login and send it now if online."""
    if account is None:
        return
    pending = list(account.db.pending_notifications or [])
    pending.append(
        {"message": message, "type": notification_type, "timestamp": timezone.now().isoformat(), "read": False}
    )
    account.db.pending_notifications = pending
    if account.sessions.count():
        account.msg(message)


def start_location():
    """The room approved characters start in (settings.START_LOCATION). Raises ChargenError if missing."""
    from evennia.objects.models import ObjectDB

    dbref = str(getattr(settings, "START_LOCATION", "") or "").strip().lstrip("#")
    room = ObjectDB.objects.filter(id=int(dbref)).first() if dbref.isdigit() else None
    if room is None:
        raise ChargenError(
            f"The start location {settings.START_LOCATION!r} doesn't exist; an Admin must fix START_LOCATION "
            "before characters can be approved",
            status=409,
        )
    return room


def _open_approval_job(account, character):
    from jobs.models import Bucket, Job

    bucket, _ = Bucket.objects.get_or_create(
        name=APPROVAL_BUCKET, defaults={"description": "Character applications from the website"}
    )
    return Job.objects.create(
        title=f"Character application: {character.key}",
        description=(
            f"{account.username} applied for {character.key} (#{character.id}). "
            "Review it on the website's staff character-approval page."
        ),
        creator=account,
        bucket=bucket,
    )


# ----------------------------------------------------------------------------
# Units (run on the reactor)
# ----------------------------------------------------------------------------


def create_character_unit(account, sub):
    """Create the character, write its sheet, open its application. Returns the character.

    On any failure everything created here is removed again and the
    exception is re-raised.
    """
    character = bio = job = None
    try:
        character, errors = character_class().create(sub.name, account=account)
        if errors or character is None:
            raise ChargenError(errors or ["The character couldn't be created"])
        apply_chargen(character, sub)
        bio = CharacterBio.objects.create(
            character=character,
            account=account,
            status="submitted",
            full_name=sub.name,
            concept=sub.concept,
            sire=sub.sire,
            ambition=sub.ambition,
            desire=sub.desire,
            background=sub.background,
            submission=sub.as_dict(),
        )
        job = _open_approval_job(account, character)
    except Exception:
        _undo_create(account, character, bio, job)
        raise
    return character


def _undo_create(account, character, bio, job):
    for step in (
        lambda: job and job.pk and job.delete(),
        lambda: bio and bio.pk and CharacterBio.objects.filter(pk=bio.pk).delete(),
        lambda: character and account.characters.remove(character),
        lambda: character and character.pk and character.delete(),
    ):
        try:
            step()
        except Exception:
            logger.log_trace("Chargen: undoing a failed character creation")


def approve_unit(bio_id, reviewer, notes=""):
    """Place the character in the start room, then mark the application approved."""
    bio = CharacterBio.objects.select_related("character", "account").get(pk=bio_id)
    if not bio.can_transition("approved"):
        raise ChargenError(f"An application that is {bio.status} can't be approved", status=409)
    room = start_location()
    character = bio.character
    old_home, old_location = character.home, character.location
    character.home = room
    character.move_to(room, quiet=True, move_type="teleport")
    try:
        bio.transition("approved", by=reviewer)
    except Exception:
        character.home = old_home
        character.location = old_location
        raise
    notify_account(
        bio.account,
        f"Your character '{character.key}' has been APPROVED. You may now play: |wic {character.key}|n"
        + (f"\nStaff notes: {notes}" if notes else ""),
        notification_type="approval",
    )
    return bio


def reject_unit(bio_id, reviewer, notes):
    bio = CharacterBio.objects.select_related("character", "account").get(pk=bio_id)
    if not bio.can_transition("rejected"):
        raise ChargenError(f"An application that is {bio.status} can't be rejected", status=409)
    bio.transition("rejected", by=reviewer, rejection_notes=notes, rejection_count=F("rejection_count") + 1)
    notify_account(
        bio.account,
        f"Your character '{bio.character.key}' needs revisions.\nStaff feedback:\n{notes}\n"
        "Edit and resubmit it on the website's character creation page.",
        notification_type="rejection",
    )
    return bio


def revoke_unit(bio_id, reviewer, notes):
    """Mark an approved character revoked, then take it away from anyone playing it."""
    bio = CharacterBio.objects.select_related("character", "account").get(pk=bio_id)
    if not bio.can_transition("revoked"):
        raise ChargenError(f"An application that is {bio.status} can't be revoked", status=409)
    bio.transition("revoked", by=reviewer, rejection_notes=notes)
    character = bio.character
    for session in list(character.sessions.all()):
        puppeteer = session.account or character.account
        if puppeteer:
            puppeteer.unpuppet_object(session)
            puppeteer.msg(f"|rStaff revoked approval of {character.key}.|n {notes}".strip(), session=session)
    notify_account(
        bio.account,
        f"Approval of your character '{character.key}' was revoked.\n{notes}\n"
        "You can edit and resubmit it on the website's character creation page.",
        notification_type="revocation",
    )
    return bio


def resubmit_unit(bio_id, account, sub):
    """Replace the sheet with a validated resubmission and put it back in the queue."""
    bio = CharacterBio.objects.select_related("character").get(pk=bio_id)
    if bio.account_id != account.id:
        raise ChargenError("Only the owner can resubmit this character", status=403)
    if not bio.can_transition("submitted"):
        raise ChargenError(f"An application that is {bio.status} can't be resubmitted", status=409)
    character = bio.character
    if sub.name.lower() != character.key.lower() and name_taken(sub.name, exclude_id=character.id):
        raise ChargenError(f"A character named '{sub.name}' already exists")

    snapshot, old_key = character.snapshot_sheet(), character.key
    try:
        character.reset_sheet()
        apply_chargen(character, sub)
        if sub.name != character.key:
            character.key = sub.name
        bio.transition(
            "submitted",
            full_name=sub.name,
            concept=sub.concept,
            sire=sub.sire,
            ambition=sub.ambition,
            desire=sub.desire,
            background=sub.background,
            submission=sub.as_dict(),
            rejection_notes="",
        )
    except Exception:
        character.restore_sheet(snapshot)
        if character.key != old_key:
            character.key = old_key
        raise
    return bio
