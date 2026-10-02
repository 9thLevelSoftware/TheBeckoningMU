"""
traits.CharacterBio: ownership, approval and narrative for a character
application from the website.

V5 rules data lives in world/v5_data.py and character traits in the
character's Attributes (typeclasses/characters.py); there are no trait
tables.
"""

from django.db import models
from evennia.objects.models import ObjectDB


class CharacterBio(models.Model):
    """
    A character's application: who owns it, where approval stands, and the
    narrative the player wrote.

    This is the only record of ownership (`account`) and approval (`status`);
    the char_owner()/char_approved() lockfuncs read it. Game facts such as
    clan, generation and predator type live on the character, behind the
    Character accessors, not here.
    """

    character = models.OneToOneField(ObjectDB, on_delete=models.CASCADE, related_name='vtm_bio')

    # Core VtM 5e background
    full_name = models.CharField(max_length=200, blank=True, help_text="Character's full name")
    concept = models.CharField(max_length=100, blank=True, help_text="Character concept")
    ambition = models.TextField(blank=True, help_text="Character's driving ambition")
    desire = models.TextField(blank=True, help_text="Character's immediate desire")

    sire = models.CharField(max_length=100, blank=True, help_text="Character's sire")

    # Ownership: the account that applied for this character. This is the
    # one ownership fact (the char_owner() lockfunc reads it); it is never
    # the character's current puppeteer (db_account).
    account = models.ForeignKey(
        'accounts.AccountDB',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='character_bios',
        help_text="Account that owns this character",
    )

    # Status lifecycle
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('rejected', 'Rejected'),
        ('approved', 'Approved'),
        ('revoked', 'Revoked'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='submitted',
        help_text="Current approval status"
    )
    background = models.TextField(
        blank=True,
        help_text="Character's backstory/background narrative"
    )
    rejection_notes = models.TextField(
        blank=True,
        help_text="Staff feedback on why character was rejected"
    )
    rejection_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times this character has been rejected"
    )

    # Review record: the staff member who made the last approve, reject or
    # revoke decision, and when.
    reviewed_by = models.ForeignKey(
        'accounts.AccountDB',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_character_bios',
        help_text="Staff account that made the last review decision",
    )
    reviewed_at = models.DateTimeField(blank=True, null=True, help_text="When the last review decision was made")

    # The application as last submitted (world.rules_chargen.Submission.as_dict()).
    # It prefills the edit form after a rejection and shows staff what was
    # asked for. It is never read as the character sheet: the sheet lives in
    # the character's Attributes, behind the Character accessors.
    submission = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Allowed status changes: {(from, to): permission the actor needs}.
    # "owner" means the owning account; the others are Evennia permissions.
    TRANSITIONS = {
        ('submitted', 'approved'): 'Builder',
        ('submitted', 'rejected'): 'Builder',
        ('rejected', 'submitted'): 'owner',
        ('approved', 'revoked'): 'Admin',
        ('revoked', 'submitted'): 'owner',
    }
    REVIEW_STATUSES = ('approved', 'rejected', 'revoked')

    class TransitionError(Exception):
        """The status change isn't allowed from the current status (or it changed meanwhile)."""

    class Meta:
        app_label = 'traits'

    def __str__(self):
        return f"{self.character.db_key}'s Bio ({self.status})"

    def can_transition(self, to):
        return (self.status, to) in self.TRANSITIONS

    def transition(self, to, by=None, **fields):
        """Move to status `to`, recording the reviewer for staff decisions.

        The write is conditional on the status this instance holds, so two
        reviewers acting at once can't both succeed. Raises TransitionError
        if the change isn't in TRANSITIONS or the stored status has moved on.
        Extra `fields` (e.g. rejection_notes) are written in the same update.
        """
        from django.utils import timezone

        if not self.can_transition(to):
            raise self.TransitionError(f"Can't go from {self.status} to {to}")
        values = dict(fields, status=to, updated_at=timezone.now())
        if to in self.REVIEW_STATUSES:
            values.update(reviewed_by=by, reviewed_at=timezone.now())
        updated = CharacterBio.objects.filter(pk=self.pk, status=self.status).update(**values)
        if not updated:
            raise self.TransitionError(f"{self.character.db_key}'s application changed meanwhile")
        self.refresh_from_db()
        return self
