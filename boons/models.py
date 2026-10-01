"""
Django Models for Boons System

Tracks political favors and debts (Prestation) in Kindred society.
"""

from django.db import models
from evennia.typeclasses.models import SharedMemoryModel

# A boon is owed from acceptance until it is fulfilled, called in or not.
OUTSTANDING_STATUSES = ("accepted", "called_in")
TERMINAL_STATUSES = ("fulfilled", "declined", "canceled")
BOON_WEIGHTS = {"trivial": 1, "minor": 2, "major": 3, "blood": 4, "life": 5}


class Boon(SharedMemoryModel):
    """
    Represents a boon (favor/debt) between two characters.

    In Vampire society, boons are the currency of influence. They represent
    favors owed and debts to be repaid, tracked meticulously by Harpies.

    Lifecycle: the debtor offers (offered); the creditor accepts (accepted)
    or declines (declined); the creditor calls it in (called_in); it is
    fulfilled when both parties confirm (fulfilled). Staff may cancel or
    force fulfilment. A boon is outstanding while accepted or called in.
    """

    # Boon participants
    debtor = models.ForeignKey(
        'objects.ObjectDB',
        on_delete=models.CASCADE,
        related_name='boons_owed',
        help_text="Character who owes the boon"
    )

    creditor = models.ForeignKey(
        'objects.ObjectDB',
        on_delete=models.CASCADE,
        related_name='boons_held',
        help_text="Character to whom the boon is owed"
    )

    # Boon type/level
    BOON_TYPES = [
        ('trivial', 'Trivial'),
        ('minor', 'Minor'),
        ('major', 'Major'),
        ('blood', 'Blood Boon'),
        ('life', 'Life Boon')
    ]

    boon_type = models.CharField(
        max_length=20,
        choices=BOON_TYPES,
        default='minor',
        help_text="Level/importance of the boon"
    )

    # Boon details
    description = models.TextField(
        help_text="Description of the favor that created this boon"
    )

    # Status tracking
    STATUS_CHOICES = [
        ('offered', 'Offered'),
        ('accepted', 'Accepted'),
        ('called_in', 'Called In'),
        ('fulfilled', 'Fulfilled'),
        ('declined', 'Declined'),
        ('canceled', 'Canceled'),
        ('disputed', 'Disputed')
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='offered',
        help_text="Current status of the boon"
    )

    # Social tracking
    witnesses = models.ManyToManyField(
        'objects.ObjectDB',
        related_name='witnessed_boons',
        blank=True,
        help_text="Characters who witnessed this boon's creation"
    )

    acknowledged_by_harpy = models.BooleanField(
        default=False,
        help_text="Whether a Harpy has officially acknowledged this boon"
    )

    harpy = models.ForeignKey(
        'objects.ObjectDB',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_boons',
        help_text="Harpy who acknowledged this boon"
    )

    # Fulfillment tracking
    called_in_description = models.TextField(
        blank=True,
        help_text="Description of how the boon was called in"
    )

    fulfillment_description = models.TextField(
        blank=True,
        help_text="Description of how the boon was fulfilled"
    )

    # A called-in boon is fulfilled once both parties confirm it.
    debtor_confirmed = models.BooleanField(
        default=False,
        help_text="The debtor has confirmed the called-in favor was done"
    )
    creditor_confirmed = models.BooleanField(
        default=False,
        help_text="The creditor has confirmed the called-in favor was done"
    )

    # Public/Private
    is_public = models.BooleanField(
        default=True,
        help_text="Whether this boon is publicly known"
    )

    # Notes
    staff_notes = models.TextField(
        blank=True,
        help_text="Staff notes about this boon"
    )

    # Timestamps
    created_date = models.DateTimeField(auto_now_add=True)
    accepted_date = models.DateTimeField(null=True, blank=True)
    called_in_date = models.DateTimeField(null=True, blank=True)
    fulfilled_date = models.DateTimeField(null=True, blank=True)
    modified_date = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'boons'
        verbose_name = "Boon"
        verbose_name_plural = "Boons"
        ordering = ['-created_date']

    def __str__(self):
        return f"{self.debtor.key} owes {self.creditor.key} a {self.get_boon_type_display()} boon"

    def accept(self):
        """Accept an offered boon."""
        from django.utils import timezone

        if self.status != 'offered':
            return (False, "This boon has already been accepted or is no longer available.")

        self.status = 'accepted'
        self.accepted_date = timezone.now()
        self.save()

        return (True, f"Boon accepted. {self.debtor.key} now owes {self.creditor.key}.")

    def decline(self, reason=""):
        """Decline an offered boon."""
        if self.status != 'offered':
            return (False, "This boon cannot be declined in its current state.")

        self.status = 'declined'
        if reason:
            self.fulfillment_description = f"Declined: {reason}"
        self.save()

        return (True, "Boon declined.")

    def call_in(self, description):
        """Call in an accepted boon."""
        from django.utils import timezone

        if self.status != 'accepted':
            return (False, "This boon must be accepted before it can be called in.")

        self.status = 'called_in'
        self.called_in_description = description
        self.called_in_date = timezone.now()
        self.save()

        return (True, f"Boon called in: {description}")

    def confirm_fulfilled(self, character, description=""):
        """
        Record one party's confirmation that a called-in boon was repaid.

        The boon becomes fulfilled only when both the debtor and the
        creditor have confirmed.
        """
        if self.status != 'called_in':
            return (False, "Only a boon that has been called in can be fulfilled.")
        if character == self.debtor:
            self.debtor_confirmed = True
        elif character == self.creditor:
            self.creditor_confirmed = True
        else:
            return (False, "Only the debtor or creditor can confirm this boon.")

        if description:
            self.fulfillment_description = description
        if self.debtor_confirmed and self.creditor_confirmed:
            return self.fulfill(self.fulfillment_description)

        self.save()
        other = self.creditor if character == self.debtor else self.debtor
        return (True, f"Fulfilment confirmed. Waiting for {other.key} to confirm.")

    def fulfill(self, description=""):
        """Mark a boon fulfilled (both parties confirmed, or a staff override)."""
        from django.utils import timezone

        if self.status not in OUTSTANDING_STATUSES:
            return (False, "This boon is not in a state to be fulfilled.")

        self.status = 'fulfilled'
        if description:
            self.fulfillment_description = description
        self.fulfilled_date = timezone.now()
        self.save()

        return (True, "Boon fulfilled.")

    def dispute(self, reason):
        """Dispute an outstanding boon (requires Harpy intervention)."""
        if self.status not in OUTSTANDING_STATUSES:
            return (False, "Only an accepted or called-in boon can be disputed.")
        self.status = 'disputed'
        if not self.fulfillment_description:
            self.fulfillment_description = f"Disputed: {reason}"
        else:
            self.fulfillment_description += f"\nDisputed: {reason}"
        self.save()

        return (True, "Boon disputed. A Harpy must adjudicate.")

    def cancel(self, reason=""):
        """Cancel a boon (typically by mutual agreement or Harpy ruling)."""
        if self.status in TERMINAL_STATUSES:
            return (False, f"This boon is already {self.status}.")
        self.status = 'canceled'
        if reason:
            self.fulfillment_description = f"Canceled: {reason}"
        self.save()

        return (True, "Boon canceled.")

    def acknowledge_by_harpy(self, harpy_character):
        """Officially acknowledge this boon (Harpy function)."""
        self.acknowledged_by_harpy = True
        self.harpy = harpy_character
        self.save()

        return (True, f"Boon acknowledged by Harpy {harpy_character.key}.")

    def get_boon_weight(self):
        """
        Get numerical weight of boon for calculation purposes.

        Returns:
            int: Weight value (1-5)
        """
        return BOON_WEIGHTS.get(self.boon_type, 2)
