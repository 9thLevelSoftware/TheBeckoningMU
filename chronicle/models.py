from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone
from evennia.objects.models import ObjectDB


class ChronicleEvent(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PARTICIPANTS = "participants", "Participants"
        STAFF = "staff", "Staff only"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        SUPERSEDED = "superseded", "Superseded"
        REDACTED = "redacted", "Redacted"
        DISCARDED = "discarded", "Discarded"
        WITHDRAWN = "withdrawn", "Withdrawn for source review"

    class LineageStatus(models.TextChoices):
        KNOWN = "known", "Known"
        UNKNOWN = "unknown", "Needs source review"

    idempotency_key = models.CharField(max_length=200, unique=True)
    source_app = models.CharField(max_length=64)
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=80)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chronicle_events_created",
    )
    participants = models.ManyToManyField(ObjectDB, blank=True, related_name="chronicle_events")
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PARTICIPANTS)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chronicle_events_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    redacted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chronicle_events_redacted",
    )
    redacted_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="corrections",
    )
    supersedes_version = models.PositiveIntegerField(null=True, blank=True)
    revision_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="revisions")
    discarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chronicle_events_discarded",
    )
    discarded_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chronicle_events_withdrawn",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.CharField(max_length=80, blank=True)
    lineage_status = models.CharField(max_length=8, choices=LineageStatus.choices, default=LineageStatus.KNOWN)
    lineage_note = models.CharField(max_length=80, blank=True)
    ai_generated = models.BooleanField(default=False)
    source_events = models.ManyToManyField("self", blank=True, symmetrical=False, related_name="derived_events")

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["status", "visibility", "occurred_at"]),
            models.Index(fields=["source_app", "source_type", "source_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("supersedes",),
                condition=models.Q(status="draft", supersedes__isnull=False),
                name="chronicle_one_active_correction_draft",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.kind})"


class ChronicleGenerationRequest(models.Model):
    """Durable staff drafting intent; source fingerprints contain no source prose."""

    class Mode(models.TextChoices):
        RECAP = "recap", "Recap"
        RUMOR = "rumor", "Rumor"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    request_key = models.UUIDField(default=uuid4, unique=True, editable=False)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    mode = models.CharField(max_length=8, choices=Mode.choices)
    source_ids = models.JSONField(default=list)
    source_fingerprints = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    citations = models.JSONField(default=list, blank=True)
    error = models.CharField(max_length=200, blank=True)
    draft_event = models.OneToOneField(
        ChronicleEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="generation_request"
    )
