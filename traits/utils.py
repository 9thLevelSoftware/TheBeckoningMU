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
would survive a rollback. Once a status change is committed, the follow-up
steps (notifications, job bookkeeping, unpuppeting) are best-effort: each is
logged on failure and the unit still reports the status it wrote.

Each application has an Approval-bucket job (CharacterBio.job_id): it is
opened on create, commented on every decision and resubmission, closed on
approval or when the character is deleted, reopened on revoke, and renamed
when the character is.
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


def name_problem(name, account, exclude_id=None):
    """Why `name` can't be used by `account` (database checks), or None."""
    from evennia.accounts.models import AccountDB

    if name_taken(name, exclude_id=exclude_id):
        return f"A character named '{name}' already exists"
    if AccountDB.objects.filter(username__iexact=name).exclude(id=account.id).exists():
        return f"'{name}' is another player's account name; choose another"
    return None


def active_application_count(account):
    """Pending and approved characters owned by `account`."""
    return CharacterBio.objects.filter(account=account, status__in=("submitted", "approved")).count()


def over_character_limit(account):
    """The one character cap: pending + approved applications against
    MAX_NR_CHARACTERS (rejected and revoked ones don't count; Developers and
    superusers are exempt, as in Evennia's own slot check)."""
    from web.permissions import has_perm

    limit = settings.MAX_NR_CHARACTERS
    if limit is None or has_perm(account, "Developer"):
        return None
    if active_application_count(account) >= limit:
        return limit
    return None


def _best_effort(what, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.log_trace(f"Chargen: {what} failed (the status change itself is recorded)")
        return None


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
    room = ObjectDB.objects.filter(id=int(dbref)).first() if dbref.isascii() and dbref.isdigit() else None
    if room is None:
        raise ChargenError(
            f"The start location {settings.START_LOCATION!r} doesn't exist; an Admin must fix START_LOCATION "
            "before characters can be approved",
            status=409,
        )
    return room


# ----------------------------------------------------------------------------
# The application's Approval job
# ----------------------------------------------------------------------------


def _job_title(character):
    return f"Character application: {character.key} (#{character.id})"


def _open_approval_job(account, character):
    from jobs.models import Bucket, Job

    bucket, _ = Bucket.objects.get_or_create(
        name=APPROVAL_BUCKET, defaults={"description": "Character applications from the website"}
    )
    return Job.objects.create(
        title=_job_title(character),
        description=(
            f"{account.username} applied for {character.key} (#{character.id}). "
            "Review it on the website's staff character-approval page."
        ),
        creator=account,
        bucket=bucket,
    )


def application_job(bio):
    from jobs.models import Job

    return Job.objects.filter(id=bio.job_id).first() if bio.job_id else None


def job_event(bio, author, text, status=None):
    """Comment on the application's job, and open or close it (status "OPEN"/"CLOSED")."""
    from jobs.models import Comment

    job = application_job(bio)
    if job is None:
        return None
    Comment.objects.create(job=job, author=author or job.creator, content=text, public=True)
    fields = {"title": _job_title(bio.character)}
    if status == "CLOSED":
        fields.update(status="CLOSED", completed=True, resolved_at=timezone.now())
    elif status == "OPEN":
        fields.update(status="OPEN", completed=False, resolved_at=None)
    for key, value in fields.items():
        setattr(job, key, value)
    job.save()
    return job


# ----------------------------------------------------------------------------
# Units (run on the reactor)
# ----------------------------------------------------------------------------


def create_character_unit(account, sub, ip=None):
    """Create the character, write its sheet, open its application. Returns the character.

    The character is made with create_object (not Character.create), so the
    only character cap is over_character_limit(), checked by the view, and
    the gated locks are installed once, by basetype_setup. On any failure
    everything created here is removed again and the exception is re-raised.
    """
    from evennia.utils import create

    character = bio = job = None
    try:
        character = create.create_object(
            character_class(), key=sub.name, permissions=settings.PERMISSION_ACCOUNT_DEFAULT
        )
        account.characters.add(character)
        character.db.creator_id = account.id
        if ip:
            character.db.creator_ip = ip
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
            applicant_ip=ip or None,
        )
        job = _open_approval_job(account, character)
        CharacterBio.objects.filter(pk=bio.pk).update(job_id=job.id)
    except Exception:
        _undo_create(account, character, bio, job)
        raise
    return character


def _undo_create(account, character, bio, job):
    # The bio would also go with the character (CASCADE) and the job is the
    # last step; both are deleted explicitly so the undo doesn't depend on
    # the order of the steps above.
    steps = (
        ("job", lambda: job and job.pk and job.delete()),
        ("bio", lambda: bio and bio.pk and CharacterBio.objects.filter(pk=bio.pk).delete()),
        ("character list", lambda: character and account.characters.remove(character)),
        ("character", lambda: character and character.pk and character.delete()),
    )
    for what, step in steps:
        try:
            step()
        except Exception:
            logger.log_trace(f"Chargen: undoing a failed character creation ({what})")


def approve_unit(bio_id, reviewer, notes="", ip=None):
    """Place the character in the start room, then mark the application approved."""
    bio = CharacterBio.objects.select_related("character", "account").get(pk=bio_id)
    if not bio.can_transition("approved"):
        raise ChargenError(f"An application that is {bio.status} can't be approved", status=409)
    room = start_location()
    character = bio.character
    old_home, old_location = character.home, character.location
    try:
        character.home = room
        if not character.move_to(room, quiet=True, move_type="teleport"):
            raise ChargenError(f"{character.key} couldn't be moved to the start location", status=500)
        bio.transition("approved", by=reviewer, reviewer_ip=ip)
    except Exception:
        character.home = old_home
        character.location = old_location
        raise
    message = f"Your character '{character.key}' has been APPROVED. You may now play: |wic {character.key}|n"
    if notes:
        message += f"\nStaff notes: {notes}"
    _best_effort("approval notification", notify_account, bio.account, message, notification_type="approval")
    _best_effort(
        "approval job", job_event, bio, reviewer, f"Approved by {reviewer.username}. {notes}".strip(), "CLOSED"
    )
    return bio


def reject_unit(bio_id, reviewer, notes, ip=None):
    bio = CharacterBio.objects.select_related("character", "account").get(pk=bio_id)
    if not bio.can_transition("rejected"):
        raise ChargenError(f"An application that is {bio.status} can't be rejected", status=409)
    bio.transition(
        "rejected", by=reviewer, reviewer_ip=ip, rejection_notes=notes, rejection_count=F("rejection_count") + 1
    )
    _best_effort(
        "rejection notification",
        notify_account,
        bio.account,
        f"Your character '{bio.character.key}' needs revisions.\nStaff feedback:\n{notes}\n"
        "Edit and resubmit it on the website's character creation page.",
        notification_type="rejection",
    )
    _best_effort("rejection job", job_event, bio, reviewer, f"Rejected by {reviewer.username}: {notes}")
    return bio


def revoke_unit(bio_id, reviewer, notes, ip=None):
    """Mark an approved character revoked, then take it away from anyone playing it.

    The status write comes first, so re-puppeting is refused whatever
    happens next; each session is then unpuppeted on its own.
    """
    bio = CharacterBio.objects.select_related("character", "account").get(pk=bio_id)
    if not bio.can_transition("revoked"):
        raise ChargenError(f"An application that is {bio.status} can't be revoked", status=409)
    bio.transition("revoked", by=reviewer, reviewer_ip=ip, rejection_notes=notes)
    character = bio.character
    for session in list(character.sessions.all()):
        _best_effort("unpuppeting a revoked character", _evict, character, session, notes)
    _best_effort(
        "revocation notification",
        notify_account,
        bio.account,
        f"Approval of your character '{character.key}' was revoked.\n{notes}\n"
        "Resubmit it for review on the website's character creation page; its sheet is kept.",
        notification_type="revocation",
    )
    _best_effort(
        "revocation job", job_event, bio, reviewer, f"Approval revoked by {reviewer.username}: {notes}", "OPEN"
    )
    return bio


def _evict(character, session, notes):
    puppeteer = session.account or character.account
    if puppeteer:
        puppeteer.unpuppet_object(session)
        puppeteer.msg(f"|rStaff revoked approval of {character.key}.|n {notes}".strip(), session=session)


def resubmit_unit(bio_id, account, sub):
    """Replace a rejected application's sheet with a validated resubmission.

    Only for rejected applications (never played): a revoked character keeps
    its sheet and goes through resubmit_revoked_unit.
    """
    bio = CharacterBio.objects.select_related("character").get(pk=bio_id)
    if bio.account_id != account.id:
        raise ChargenError("Only the owner can resubmit this character", status=403)
    if bio.status != "rejected":
        raise ChargenError(f"An application that is {bio.status} can't be resubmitted with a new sheet", status=409)
    character = bio.character
    if sub.name.lower() != character.key.lower():
        problem = name_problem(sub.name, account, exclude_id=character.id)
        if problem:
            raise ChargenError(problem)

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
    _best_effort("resubmission job", job_event, bio, account, f"{account.username} resubmitted the application.")
    return bio


def resubmit_revoked_unit(bio_id, account, narrative):
    """Send a revoked character back for review as it stands.

    Owner decision: revoking only pauses play. The played sheet, XP and XP
    log are kept; only the narrative fields in `narrative` may change.
    """
    bio = CharacterBio.objects.select_related("character").get(pk=bio_id)
    if bio.account_id != account.id:
        raise ChargenError("Only the owner can resubmit this character", status=403)
    if bio.status != "revoked":
        raise ChargenError(f"An application that is {bio.status} isn't revoked", status=409)
    bio.transition("submitted", **narrative)
    _best_effort(
        "resubmission job",
        job_event,
        bio,
        account,
        f"{account.username} resubmitted the revoked character for review (sheet unchanged).",
    )
    return bio


def close_job_for_deleted_character(character):
    """Called from Character.at_object_delete: close the application's job."""
    bio = CharacterBio.objects.select_related("account").filter(character_id=character.id).first()
    if bio is not None:
        _best_effort("closing the job of a deleted character", job_event, bio, bio.account,
                     f"{character.key} was deleted.", "CLOSED")  # fmt: skip
