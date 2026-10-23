"""
Jobs system models for TheBeckoningMU.

Provides a structured task/request management system with buckets,
jobs, comments, and tags following BBS-style sequence numbering.
"""

import sqlite3
import time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, connections, models, router, transaction
from django.db.models import F, Max
from evennia.accounts.models import AccountDB


class Bucket(models.Model):
    """
    A category/container for organizing jobs.
    Examples: Bugs, Features, Requests, RP, Staff
    """

    name = models.CharField(max_length=200, unique=True, help_text="Unique name of the bucket")
    description = models.TextField(help_text="Description of what this bucket is for")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(
        default=False,
        help_text="Archived buckets are hidden from normal views"
    )
    player_submit = models.BooleanField(
        default=False,
        help_text="Players may file jobs here with job/submit, and see it in 'buckets'"
    )
    created_by = models.ForeignKey(
        AccountDB,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_buckets",
        help_text="Account that created this bucket",
    )

    class Meta:
        app_label = "jobs"
        ordering = ["name"]
        verbose_name = "Job Bucket"
        verbose_name_plural = "Job Buckets"

    def __str__(self):
        return self.name


class Tag(models.Model):
    """
    Tags for categorizing jobs within buckets.
    Examples: critical, enhancement, documentation
    """

    name = models.CharField(max_length=200, unique=True, help_text="Unique tag name")

    class Meta:
        app_label = "jobs"
        ordering = ["name"]
        verbose_name = "Job Tag"
        verbose_name_plural = "Job Tags"

    def __str__(self):
        return self.name


class Job(models.Model):
    """
    A job/request/task in the system.
    Uses BBS-style sequence numbering per bucket.
    """

    STATUS_CHOICES = [("OPEN", "Open"), ("CLOSED", "Closed")]

    PRIORITY_CHOICES = [("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")]

    # Core fields
    title = models.CharField(max_length=200, help_text="Brief title of the job")
    description = models.TextField(help_text="Detailed description of the job")
    status = models.CharField(
        max_length=6, choices=STATUS_CHOICES, default="OPEN", help_text="Current status of the job"
    )
    completed = models.BooleanField(default=False, help_text="Whether the job is completed")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True, help_text="When the job was resolved/completed")
    deadline = models.DateTimeField(null=True, blank=True, help_text="Optional deadline for completion")

    # Relationships
    creator = models.ForeignKey(
        AccountDB, on_delete=models.CASCADE, related_name="jobs", help_text="Account that created this job"
    )
    assigned_to = models.ForeignKey(
        AccountDB,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="assigned_jobs",
        help_text="Primary account assigned to this job",
    )
    players = models.ManyToManyField(
        AccountDB, related_name="related_jobs", blank=True, help_text="All accounts involved in this job"
    )
    bucket = models.ForeignKey(
        Bucket, related_name="jobs", on_delete=models.CASCADE, help_text="Bucket this job belongs to"
    )
    tags = models.ManyToManyField(Tag, blank=True, help_text="Tags for categorizing this job")

    # Job management
    priority = models.CharField(
        max_length=6, choices=PRIORITY_CHOICES, default="LOW", help_text="Priority level of this job"
    )
    sequence_number = models.IntegerField(default=0, help_text="Auto-incrementing job number per bucket")

    class Meta:
        app_label = "jobs"
        ordering = ["bucket", "sequence_number"]
        unique_together = [["bucket", "sequence_number"]]
        verbose_name = "Job"
        verbose_name_plural = "Jobs"

    def __str__(self):
        return f"Job {self.sequence_number}: {self.title}"

    def clean(self):
        """Reject a priority or status that isn't one of the model's choices."""
        if self.priority not in dict(self.PRIORITY_CHOICES):
            raise ValidationError({"priority": f"Unknown priority {self.priority!r}."})
        if self.status not in dict(self.STATUS_CHOICES):
            raise ValidationError({"status": f"Unknown status {self.status!r}."})

    @property
    def ref(self):
        """The job's address, `<bucket>/<n>` (numbers are per bucket)."""
        return f"{self.bucket.name}/{self.sequence_number}"

    def save(self, *args, **kwargs):
        """
        Allocate and insert while holding the bucket's database write lock.

        Locking jobs cannot serialize the first insert into an empty bucket.
        SQLite needs a write reservation before reading MAX; PostgreSQL and
        MySQL can lock the existing parent row. Keep the insert in that same
        transaction so a second creator observes its committed number.
        """
        self.clean()
        if self.pk or self.sequence_number:
            return super().save(*args, **kwargs)

        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        connection = connections[database]
        attempts = 8 if connection.vendor == "sqlite" and not connection.in_atomic_block else 2
        for attempt in range(attempts):
            try:
                with transaction.atomic(using=database):
                    buckets = Bucket.objects.using(database)
                    if connection.vendor == "sqlite":
                        buckets.filter(pk=self.bucket_id).update(name=F("name"))
                    else:
                        buckets.select_for_update().get(pk=self.bucket_id)
                    max_seq = (
                        Job.objects.using(database)
                        .filter(bucket_id=self.bucket_id)
                        .aggregate(Max("sequence_number"))["sequence_number__max"]
                    )
                    self.sequence_number = (max_seq or 0) + 1
                    return super().save(*args, **kwargs)
            except IntegrityError:
                # Preserve the base branch's savepoint retry for a stale
                # allocation (including callers already in a transaction).
                self.sequence_number = 0
                self.pk = None
                self._state.adding = True
                if attempt:
                    raise
            except OperationalError as error:
                self.sequence_number = 0
                cause = error.__cause__
                code = getattr(cause, "sqlite_errorcode", 0) & 0xFF
                if (
                    connection.vendor != "sqlite"
                    or code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                    or connection.in_atomic_block
                    or attempt + 1 == attempts
                ):
                    raise
                # Each retry starts a new transaction, never a stale outer
                # transaction or a process-local lock that misses other servers.
                self.pk = None
                self._state.adding = True
                time.sleep(min(0.01 * 2**attempt, 0.2))


class Comment(models.Model):
    """
    A comment on a job.
    Can be public (visible to all) or private (staff only).
    """

    content = models.TextField(help_text="Content of the comment")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False, help_text="Whether this comment has been edited")
    public = models.BooleanField(default=False, help_text="Public comments are visible to all; private to staff only")

    # Relationships
    job = models.ForeignKey(
        Job, related_name="comments", on_delete=models.CASCADE, help_text="Job this comment belongs to"
    )
    author = models.ForeignKey(
        AccountDB, related_name="job_comments", on_delete=models.CASCADE, help_text="Account that created this comment"
    )

    class Meta:
        app_label = "jobs"
        ordering = ["created_at"]
        verbose_name = "Job Comment"
        verbose_name_plural = "Job Comments"

    def __str__(self):
        visibility = "Public" if self.public else "Private"
        return f"{visibility} comment by {self.author.username} on {self.job}"
