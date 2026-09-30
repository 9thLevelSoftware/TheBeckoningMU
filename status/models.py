"""
Django Models for Status System

Tracks Camarilla positions, Status ratings, and status change requests.
"""

from django.db import models
from evennia.typeclasses.models import SharedMemoryModel


class CamarillaPosition(SharedMemoryModel):
    """
    Defines a Camarilla position (Prince, Primogen, Sheriff, etc.).

    Positions grant Status and may have additional benefits/responsibilities.
    """

    # Position identification
    name = models.CharField(max_length=100, unique=True, help_text="Position name (e.g., Prince, Primogen)")
    title = models.CharField(max_length=200, blank=True, help_text="Full title (e.g., Prince of Athens)")

    # Status and hierarchy
    status_granted = models.IntegerField(default=0, help_text="Status dots granted by this position (0-5)")
    hierarchy_level = models.IntegerField(default=0, help_text="Hierarchy level (higher = more authority)")

    # Position details
    description = models.TextField(blank=True, help_text="Description of position responsibilities")
    is_unique = models.BooleanField(default=False, help_text="Only one character can hold this position")
    requires_clan = models.CharField(max_length=100, blank=True, help_text="Required clan (if any)")
    requires_status = models.IntegerField(default=0, help_text="Minimum Status required to hold this position")

    # Sect
    sect = models.CharField(
        max_length=50,
        default="Camarilla",
        choices=[
            ("Camarilla", "Camarilla"),
            ("Anarch", "Anarch"),
            ("Independent", "Independent")
        ],
        help_text="Sect this position belongs to"
    )

    # Active status
    is_active = models.BooleanField(default=True, help_text="Whether this position is currently in use")

    class Meta:
        app_label = 'status'
        verbose_name = "Camarilla Position"
        verbose_name_plural = "Camarilla Positions"
        ordering = ['-hierarchy_level', 'name']

    def __str__(self):
        return f"{self.name} ({self.sect}) - Status {self.status_granted}"


class CharacterStatus(SharedMemoryModel):
    """
    Tracks a character's Status in Kindred society.

    Status includes both earned Status (deeds, reputation) and positional Status
    (from holding a position like Primogen).
    """

    # Character reference
    character = models.OneToOneField(
        'objects.ObjectDB',
        on_delete=models.CASCADE,
        related_name='status_data',
        help_text="Character this status belongs to"
    )

    # Status ratings
    earned_status = models.IntegerField(default=0, help_text="Status earned through deeds (0-5)")
    position_status = models.IntegerField(default=0, help_text="Status from held position(s)")
    temporary_status = models.IntegerField(default=0, help_text="Temporary Status modifiers")

    # Position held
    position = models.ForeignKey(
        CamarillaPosition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='holders',
        help_text="Current Camarilla position held (if any)"
    )

    # Additional positions/titles (stored as JSON)
    additional_positions = models.JSONField(
        default=list,
        blank=True,
        help_text="Additional positions/titles held (e.g., Primogen of Clan Ventrue)"
    )

    # Sect affiliation
    sect = models.CharField(
        max_length=50,
        default="Camarilla",
        choices=[
            ("Camarilla", "Camarilla"),
            ("Anarch", "Anarch"),
            ("Independent", "Independent"),
            ("Autarkis", "Autarkis")
        ],
        help_text="Sect affiliation"
    )

    # Reputation
    reputation = models.TextField(blank=True, help_text="Public reputation/known deeds")

    # Status history (stored as JSON)
    status_history = models.JSONField(
        default=list,
        blank=True,
        help_text="History of status changes"
    )

    # Timestamps
    created_date = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'status'
        verbose_name = "Character Status"
        verbose_name_plural = "Character Status Records"

    def __str__(self):
        return f"{self.character.key} - Status {self.total_status}"

    @property
    def total_status(self):
        """Calculate total Status (earned + position + temporary)."""
        return max(0, min(5, self.earned_status + self.position_status + self.temporary_status))

    def get_status_bonus(self):
        """
        Get dice bonus from Status for social rolls.

        Returns +1 die per 2 Status dots (rounded down).
        """
        return self.total_status // 2

    def add_status_history(self, change, reason, changed_by=None):
        """
        Add entry to status history.

        Args:
            change (int): Status change amount (+/-)
            reason (str): Reason for change
            changed_by (str, optional): Who made the change
        """
        from datetime import datetime

        entry = {
            "date": datetime.now().isoformat(),
            "change": change,
            "reason": reason,
            "changed_by": changed_by,
            "new_total": self.total_status
        }

        if not self.status_history:
            self.status_history = []

        self.status_history.append(entry)
        self.save()


class StatusRequest(SharedMemoryModel):
    """
    Tracks requests for Status changes or position appointments.

    Players submit requests, staff approve/deny them.
    """

    # Request identification
    character = models.ForeignKey(
        'objects.ObjectDB',
        on_delete=models.CASCADE,
        related_name='status_requests',
        help_text="Character requesting status change"
    )

    # Request type
    request_type = models.CharField(
        max_length=50,
        choices=[
            ("earned_status", "Earned Status Change"),
            ("position", "Position Appointment"),
            ("position_removal", "Position Removal"),
            ("sect_change", "Sect Change"),
            ("other", "Other")
        ],
        help_text="Type of status request"
    )

    # Request details
    requested_change = models.IntegerField(default=0, help_text="Requested status change (+/-)")
    requested_position = models.ForeignKey(
        CamarillaPosition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Requested position (if applicable)"
    )

    reason = models.TextField(help_text="Reason for request / IC justification")
    ooc_notes = models.TextField(blank=True, help_text="OOC notes for staff")

    # Status
    status = models.CharField(
        max_length=20,
        default="pending",
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("denied", "Denied"),
            ("review", "Under Review")
        ],
        help_text="Request status"
    )

    # Staff response
    reviewed_by = models.ForeignKey(
        'objects.ObjectDB',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_status_requests',
        help_text="Staff member who reviewed this request"
    )

    staff_notes = models.TextField(blank=True, help_text="Staff notes/response")
    resolution_reason = models.TextField(blank=True, help_text="Reason for approval/denial")

    # Timestamps
    created_date = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(auto_now=True)
    resolved_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'status'
        verbose_name = "Status Request"
        verbose_name_plural = "Status Requests"
        ordering = ['-created_date']

    def __str__(self):
        return f"{self.character.key} - {self.request_type} ({self.status})"

    def approve(self, staff_member, reason=""):
        """
        Approve the status request.

        Args:
            staff_member: Staff character object
            reason (str): Reason for approval
        """
        from django.utils import timezone

        self.status = "approved"
        self.reviewed_by = staff_member
        self.resolution_reason = reason
        self.resolved_date = timezone.now()
        self.save()

        # Apply the change
        self._apply_change()

    def deny(self, staff_member, reason=""):
        """
        Deny the status request.

        Args:
            staff_member: Staff character object
            reason (str): Reason for denial
        """
        from django.utils import timezone

        self.status = "denied"
        self.reviewed_by = staff_member
        self.resolution_reason = reason
        self.resolved_date = timezone.now()
        self.save()

    def _apply_change(self):
        """Apply the approved status change to the character."""
        from .utils import get_or_create_character_status

        char_status = get_or_create_character_status(self.character)

        if self.request_type == "earned_status":
            char_status.earned_status = max(0, min(5, char_status.earned_status + self.requested_change))
            char_status.add_status_history(
                self.requested_change,
                self.reason,
                str(self.reviewed_by) if self.reviewed_by else "System"
            )
            char_status.save()

        elif self.request_type == "position":
            if self.requested_position:
                # Remove from old position if unique
                if self.requested_position.is_unique:
                    # Clear any existing holder
                    old_holders = CharacterStatus.objects.filter(position=self.requested_position)
                    for old_holder in old_holders:
                        old_holder.position = None
                        old_holder.position_status = 0
                        old_holder.save()

                # Assign new position
                char_status.position = self.requested_position
                char_status.position_status = self.requested_position.status_granted
                char_status.add_status_history(
                    self.requested_position.status_granted,
                    f"Appointed to position: {self.requested_position.name}",
                    str(self.reviewed_by) if self.reviewed_by else "System"
                )
                char_status.save()

        elif self.request_type == "position_removal":
            char_status.position = None
            char_status.position_status = 0
            char_status.add_status_history(
                0,
                f"Removed from position",
                str(self.reviewed_by) if self.reviewed_by else "System"
            )
            char_status.save()

        elif self.request_type == "sect_change":
            # Sect change would be handled here
            # May require additional logic based on game rules
            pass
