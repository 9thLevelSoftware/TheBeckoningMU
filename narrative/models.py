from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from evennia.objects.models import ObjectDB


class NarrativePersona(models.Model):
    """Staff-registered persistent NPC identity; never generated prey."""

    character = models.OneToOneField(ObjectDB, on_delete=models.CASCADE, related_name="narrative_persona")
    profile = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="narrative_personas_updated",
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registered_narrative_personas",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class NarrativeConsent(models.Model):
    account = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="narrative_consents")
    character = models.ForeignKey(ObjectDB, on_delete=models.CASCADE, related_name="narrative_consents")
    opted_in = models.BooleanField(default=False)
    opted_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("account", "character"), name="narrative_consent_account_character_uniq")
        ]

    def set_opt_in(self, enabled):
        self.opted_in = enabled
        self.opted_in_at = timezone.now() if enabled else None
        self.save(update_fields=("opted_in", "opted_in_at"))
        if not enabled:
            from .services import terminate_session_requests

            sessions = self.character.narrative_sessions.filter(status=StorySession.Status.ACTIVE)
            session_ids = list(sessions.values_list("id", flat=True))
            sessions.update(status=StorySession.Status.CLOSED, closed_at=timezone.now(), current_action="")
            terminate_session_requests(session_ids, "Consent withdrawn.")


class MemoryFact(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private to subject"
        STAFF = "staff", "Staff only"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        REDACTED = "redacted", "Redacted"
        WITHDRAWN = "withdrawn", "Withdrawn for review"

    persona = models.ForeignKey(NarrativePersona, on_delete=models.CASCADE, related_name="memories")
    subject = models.ForeignKey(
        ObjectDB, null=True, blank=True, on_delete=models.CASCADE, related_name="narrative_private_memories"
    )
    text = models.TextField()
    source_event = models.ForeignKey(
        "chronicle.ChronicleEvent", null=True, blank=True, on_delete=models.PROTECT, related_name="narrative_memories"
    )
    staff_entry = models.TextField(blank=True)
    visibility = models.CharField(max_length=12, choices=Visibility.choices, default=Visibility.PRIVATE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    revision_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="revisions")
    revision_root = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="revision_family"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="memory_facts_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="memory_facts_updated"
    )
    updated_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="memory_facts_approved"
    )
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="memory_facts_withdrawn",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.CharField(max_length=80, blank=True)
    redacted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="memory_facts_redacted"
    )
    redacted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("persona", "status", "visibility", "subject", "expires_at"), name="narr_mem_scope_exp_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(status="redacted") | Q(source_event__isnull=False) | ~Q(staff_entry="")),
                name="narrative_memory_has_provenance",
            ),
            models.CheckConstraint(
                condition=(~Q(visibility="private") | Q(subject__isnull=False)),
                name="narrative_private_memory_requires_subject",
            ),
            models.UniqueConstraint(
                fields=("revision_root",),
                condition=Q(status="draft", revision_root__isnull=False),
                name="narrative_one_active_memory_revision",
            ),
        ]


class StorySession(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"

    character = models.ForeignKey(ObjectDB, on_delete=models.CASCADE, related_name="narrative_sessions")
    persona = models.ForeignKey(
        NarrativePersona, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    location = models.CharField(max_length=32, default="street")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    resume_state = models.JSONField(default=dict, blank=True)
    deterministic_outcome = models.JSONField(default=dict, blank=True)
    current_action = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("character",), condition=Q(status="active"), name="narrative_one_active_session_per_character"
            )
        ]

    def complete(self):
        from .services import terminate_session_requests

        now = timezone.now()
        self.status = self.Status.COMPLETED
        self.current_action = ""
        self.closed_at = now
        self.save(update_fields=("status", "current_action", "closed_at", "updated_at"))
        terminate_session_requests([self.pk], "Session completed.")
        self.requests.update(action_text="")


class StoryGenerationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    session = models.ForeignKey(StorySession, on_delete=models.CASCADE, related_name="requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action_text = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    response = models.TextField(blank=True)
    citations = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("session",), condition=Q(status="pending"), name="narrative_one_pending_request_per_session"
            )
        ]

    def save(self, *args, **kwargs):
        # Bind queued work even when created directly by a durable job producer.
        if self._state.adding and self.requested_by_id is None:
            from traits.models import CharacterBio

            self.requested_by_id = (
                CharacterBio.objects.filter(character_id=self.session.character_id)
                .values_list("account_id", flat=True)
                .first()
            )
        return super().save(*args, **kwargs)
