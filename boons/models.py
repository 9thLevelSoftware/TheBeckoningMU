"""
Django Models for Boons System

Tracks political favors and debts (Prestation) in Kindred society.
"""

from django.db import models
from evennia.typeclasses.models import SharedMemoryModel


class Boon(SharedMemoryModel):
    """
    Represents a boon (favor/debt) between two characters.

    In Vampire society, boons are the currency of influence. They represent
    favors owed and debts to be repaid, tracked meticulously by Harpies.
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

    def fulfill(self, description):
        """Mark a boon as fulfilled."""
        from django.utils import timezone

        if self.status not in ['accepted', 'called_in']:
            return (False, "This boon is not in a state to be fulfilled.")

        self.status = 'fulfilled'
        self.fulfillment_description = description
        self.fulfilled_date = timezone.now()
        self.save()

        return (True, "Boon fulfilled.")

    def dispute(self, reason):
        """Dispute a boon (requires Harpy intervention)."""
        self.status = 'disputed'
        if not self.fulfillment_description:
            self.fulfillment_description = f"Disputed: {reason}"
        else:
            self.fulfillment_description += f"\nDisputed: {reason}"
        self.save()

        return (True, "Boon disputed. A Harpy must adjudicate.")

    def cancel(self, reason=""):
        """Cancel a boon (typically by mutual agreement or Harpy ruling)."""
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
        weights = {
            'trivial': 1,
            'minor': 2,
            'major': 3,
            'blood': 4,
            'life': 5
        }
        return weights.get(self.boon_type, 2)


class BoonLedger(SharedMemoryModel):
    """
    Summary ledger for a character's boons (cached for performance).

    This is automatically updated when boons change.
    """

    character = models.OneToOneField(
        'objects.ObjectDB',
        on_delete=models.CASCADE,
        related_name='boon_ledger',
        help_text="Character this ledger belongs to"
    )

    # Owed counts (debts)
    trivial_owed = models.IntegerField(default=0)
    minor_owed = models.IntegerField(default=0)
    major_owed = models.IntegerField(default=0)
    blood_owed = models.IntegerField(default=0)
    life_owed = models.IntegerField(default=0)

    # Held counts (credits)
    trivial_held = models.IntegerField(default=0)
    minor_held = models.IntegerField(default=0)
    major_held = models.IntegerField(default=0)
    blood_held = models.IntegerField(default=0)
    life_held = models.IntegerField(default=0)

    # Totals (weighted)
    total_debt_weight = models.IntegerField(default=0, help_text="Total weight of boons owed")
    total_credit_weight = models.IntegerField(default=0, help_text="Total weight of boons held")
    net_weight = models.IntegerField(default=0, help_text="Net boon position (credit - debt)")

    # Timestamps
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'boons'
        verbose_name = "Boon Ledger"
        verbose_name_plural = "Boon Ledgers"

    def __str__(self):
        return f"{self.character.key}'s Boon Ledger (Net: {self.net_weight})"

    def recalculate(self):
        """Recalculate ledger from actual boons."""
        # Count owed boons
        owed_boons = Boon.objects.filter(
            debtor=self.character,
            status='accepted'
        )

        self.trivial_owed = owed_boons.filter(boon_type='trivial').count()
        self.minor_owed = owed_boons.filter(boon_type='minor').count()
        self.major_owed = owed_boons.filter(boon_type='major').count()
        self.blood_owed = owed_boons.filter(boon_type='blood').count()
        self.life_owed = owed_boons.filter(boon_type='life').count()

        # Count held boons
        held_boons = Boon.objects.filter(
            creditor=self.character,
            status='accepted'
        )

        self.trivial_held = held_boons.filter(boon_type='trivial').count()
        self.minor_held = held_boons.filter(boon_type='minor').count()
        self.major_held = held_boons.filter(boon_type='major').count()
        self.blood_held = held_boons.filter(boon_type='blood').count()
        self.life_held = held_boons.filter(boon_type='life').count()

        # Calculate weights
        weights = {'trivial': 1, 'minor': 2, 'major': 3, 'blood': 4, 'life': 5}

        self.total_debt_weight = sum([
            self.trivial_owed * weights['trivial'],
            self.minor_owed * weights['minor'],
            self.major_owed * weights['major'],
            self.blood_owed * weights['blood'],
            self.life_owed * weights['life']
        ])

        self.total_credit_weight = sum([
            self.trivial_held * weights['trivial'],
            self.minor_held * weights['minor'],
            self.major_held * weights['major'],
            self.blood_held * weights['blood'],
            self.life_held * weights['life']
        ])

        self.net_weight = self.total_credit_weight - self.total_debt_weight

        self.save()

        return (self.total_debt_weight, self.total_credit_weight, self.net_weight)
