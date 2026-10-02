import copy

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone

from web.permissions import has_perm


class StaleReviewError(ValueError):
    """The project changed (status or version) since the reviewer saw it."""


class BuildProject(models.Model):
    """
    Represents a building project (an area/zone).
    Stores the entire map state as a JSON blob.
    """

    # Status lifecycle choices
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("built", "Built"),
        ("live", "Live"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="build_projects",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # Stores the entire frontend state: rooms, exits, objects, triggers, coords
    map_data = models.JSONField(default=dict)
    # Snapshot taken at approval: {"map_data", "connection_room_id",
    # "connection_direction"}. The sandbox build reads this, never map_data,
    # so what reaches the game is exactly what the reviewer approved.
    approved_map_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Snapshot of map_data and connection taken at approval",
    )
    # Visibility to other builders
    is_public = models.BooleanField(default=True)
    # Optimistic concurrency version -- incremented on each save
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency version -- incremented on each save",
    )
    # Status lifecycle field
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        help_text="Project status in the approval/build lifecycle",
    )
    # Rejection tracking
    rejection_notes = models.TextField(
        blank=True, help_text="Notes from staff when rejecting a project"
    )
    rejection_count = models.PositiveIntegerField(
        default=0, help_text="Number of times this project has been rejected"
    )
    # Review tracking
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_build_projects",
        help_text="Staff member who last reviewed this project",
    )
    reviewed_at = models.DateTimeField(
        null=True, blank=True, help_text="When the project was last reviewed"
    )
    # Builder's notes when submitting
    submission_notes = models.TextField(
        blank=True, help_text="Builder's notes when submitting for review"
    )
    # The sandbox's entry room (if built). There is no container room.
    sandbox_room_id = models.IntegerField(null=True, blank=True)
    # Every object the sandbox build created: {"rooms": {web_id: dbid},
    # "exits": {web_id: dbid}, "scripts": [dbid, ...], "entry": dbid}.
    # Promotion and cleanup act only on these ids (never on tags alone,
    # which any Builder can forge); promotion clears it.
    built_object_ids = models.JSONField(
        default=dict,
        blank=True,
        help_text="Ids of the objects the sandbox build created",
    )
    # Connection point for promotion to live world
    connection_room_id = models.IntegerField(
        null=True, blank=True, help_text="Live room dbref to connect this build to"
    )
    connection_direction = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Direction from live room into this build (n/s/e/w/ne/nw/se/sw/u/d)",
    )
    # When promoted to live
    promoted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "builder"
        ordering = ["-updated_at"]

    def __str__(self):
        status_display = self.get_status_display()
        return f"{self.name} ({status_display}) by {self.user.username}"

    def is_editable(self):
        """Map edits are allowed only before review (draft, which includes
        projects returned by a rejection)."""
        return self.status == "draft"

    def can_be_reviewed_by(self, user):
        """
        Builders and below may never review their own project; Admins and
        above (including superusers) may. The reviewer is always recorded.
        """
        if not has_perm(user, "Builder"):
            return False
        return user != self.user or has_perm(user, "Admin")

    def can_transition_to(self, new_status):
        """
        Check if a status transition is valid.
        Valid transitions:
        - draft -> submitted
        - submitted -> approved
        - submitted -> draft (rejection)
        - approved -> built
        - built -> live
        - live -> built (demotion)
        - built -> approved (sandbox deletion)
        """
        valid_transitions = {
            "draft": ["submitted"],
            "submitted": ["approved", "draft"],
            "approved": ["built"],
            "built": ["live", "approved"],
            "live": ["built"],
        }
        return new_status in valid_transitions.get(self.status, [])

    def submit(self):
        """
        Submit a draft project for staff review.
        Transitions: draft -> submitted
        Clears any previous rejection notes, and saves the submission notes
        and the connection point set by the caller.

        Bumps `version`, as a conditional update on draft-at-this-version, so
        a review card loaded before this submission (e.g. with a different
        connection room) can no longer approve it.
        """
        if not self.can_transition_to("submitted"):
            raise ValueError(f"Cannot submit project in '{self.status}' status")
        updated = BuildProject.objects.filter(
            pk=self.pk, status="draft", version=self.version
        ).update(
            status="submitted",
            rejection_notes="",
            submission_notes=self.submission_notes,
            connection_room_id=self.connection_room_id,
            connection_direction=self.connection_direction,
            version=F("version") + 1,
            updated_at=timezone.now(),
        )
        if not updated:
            raise StaleReviewError(
                "Project changed since you loaded it. Reload and submit again."
            )
        self.refresh_from_db()

    def _review_update(self, seen_version, **fields):
        """
        Apply a review transition only if the project is still submitted at
        the version the reviewer saw. Raises StaleReviewError otherwise.
        """
        updated = BuildProject.objects.filter(
            pk=self.pk, status="submitted", version=seen_version
        ).update(**fields)
        if not updated:
            raise StaleReviewError(
                "Project changed since you loaded it. Reload and review again."
            )
        self.refresh_from_db()

    def approve(self, user, version):
        """
        Approve a submitted project.
        Transitions: submitted -> approved
        `version` is the version the reviewer looked at; the approval only
        lands if the project is still submitted at that version. Records
        reviewer and timestamp, and snapshots the reviewed map and connection
        point into approved_map_data in the same write.
        """
        if not self.can_be_reviewed_by(user):
            raise PermissionError("You cannot review your own project")
        if not self.can_transition_to("approved"):
            raise ValueError(f"Cannot approve project in '{self.status}' status")
        # Snapshot what is stored at that version. The map can't change while
        # the project is submitted (saves need draft), and a reject, edit and
        # resubmit bumps the version, which the conditional update catches.
        current = (
            BuildProject.objects.filter(pk=self.pk, version=version)
            .values("map_data", "connection_room_id", "connection_direction")
            .first()
        )
        if current is None:
            raise StaleReviewError(
                "Project changed since you loaded it. Reload and review again."
            )
        now = timezone.now()
        self._review_update(
            version,
            status="approved",
            reviewed_by=user,
            reviewed_at=now,
            approved_map_data={
                "map_data": copy.deepcopy(current["map_data"]),
                "connection_room_id": current["connection_room_id"],
                "connection_direction": current["connection_direction"],
            },
            updated_at=now,
        )

    def reject(self, user, notes, version):
        """
        Reject a submitted project, returning it to draft.
        Transitions: submitted -> draft
        Only lands if the project is still submitted at `version`.
        Increments rejection count and stores notes.
        """
        if not self.can_be_reviewed_by(user):
            raise PermissionError("You cannot review your own project")
        if not self.can_transition_to("draft"):
            raise ValueError(f"Cannot reject project in '{self.status}' status")
        if not notes or not notes.strip():
            raise ValueError("Rejection notes are required")
        now = timezone.now()
        self._review_update(
            version,
            status="draft",
            rejection_notes=notes,
            rejection_count=F("rejection_count") + 1,
            # A new version, so cards loaded before the rejection go stale.
            version=F("version") + 1,
            reviewed_by=user,
            reviewed_at=now,
            updated_at=now,
        )

    def mark_built(self):
        """
        Mark an approved project as built (sandbox created).
        Transitions: approved -> built
        """
        if not self.can_transition_to("built"):
            raise ValueError(f"Cannot mark as built from '{self.status}' status")
        self.status = "built"
        self.save(update_fields=["status", "updated_at"])

    def mark_live(self):
        """
        Mark a built project as live (promoted to production).
        Transitions: built -> live
        """
        if not self.can_transition_to("live"):
            raise ValueError(f"Cannot mark as live from '{self.status}' status")
        self.status = "live"
        self.save(update_fields=["status", "updated_at"])

    def get_default_map_data(self):
        """Return empty map data structure."""
        return {
            "schema_version": 1,
            "rooms": {},
            "exits": {},
            "objects": {},
            "next_room_id": 1,
            "next_exit_id": 1,
            "next_object_id": 1,
        }


class RoomTemplate(models.Model):
    """
    Reusable room templates with pre-configured attributes.
    """

    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="room_templates",
    )
    template_data = models.JSONField(default=dict)
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "builder"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (by {self.created_by.username})"
