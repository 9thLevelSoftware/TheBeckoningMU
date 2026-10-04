from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from evennia.objects.models import ObjectDB


class NarrativePersona(models.Model):
    """Staff-registered persistent NPC identity; never generated prey."""

    character = models.OneToOneField(ObjectDB, on_delete=models.CASCADE, related_name="narrative_persona")
    profile = models.TextField(blank=True)
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
            sessions = self.character.narrative_sessions.filter(status=StorySession.Status.ACTIVE)
            session_ids = list(sessions.values_list("id", flat=True))
            sessions.update(status=StorySession.Status.CLOSED, closed_at=timezone.now(), current_action="")
            StoryGenerationRequest.objects.filter(
                session_id__in=session_ids, status=StoryGenerationRequest.Status.PENDING
            ).update(
                status=StoryGenerationRequest.Status.FAILED,
                error="Consent withdrawn.",
                action_text="",
                completed_at=timezone.now(),
            )


class MemoryFact(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private to subject"
        STAFF = "staff", "Staff only"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        REDACTED = "redacted", "Redacted"

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

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("persona", "status", "visibility", "subject", "expires_at"), name="narr_mem_scope_exp_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(source_event__isnull=False) | ~Q(staff_entry="")),
                name="narrative_memory_has_provenance",
            ),
            models.CheckConstraint(
                condition=(~Q(visibility="private") | Q(subject__isnull=False)),
                name="narrative_private_memory_requires_subject",
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
        now = timezone.now()
        self.status = self.Status.COMPLETED
        self.current_action = ""
        self.closed_at = now
        self.save(update_fields=("status", "current_action", "closed_at", "updated_at"))
        self.requests.filter(status=StoryGenerationRequest.Status.PENDING).update(
            status=StoryGenerationRequest.Status.FAILED,
            error="Session completed.",
            action_text="",
            completed_at=now,
        )
        self.requests.update(action_text="")


class StoryGenerationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    session = models.ForeignKey(StorySession, on_delete=models.CASCADE, related_name="requests")
    action_text = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    response = models.TextField(blank=True)
    citations = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
