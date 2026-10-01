"""
Comprehensive Jobs system tests.

Tests models, utilities, and commands following BBS test patterns.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase
from evennia.accounts.models import AccountDB
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import (
    CmdBucketCreate,
    CmdBucketDelete,
    CmdBuckets,
    CmdBucketView,
    CmdJobAssign,
    CmdJobClaim,
    CmdJobComment,
    CmdJobDelete,
    CmdJobDone,
    CmdJobPublic,
    CmdJobReopen,
    CmdJobs,
    CmdJobSubmit,
    CmdJobView,
    CmdMyJobs,
)
from .models import Bucket, Comment, Job, Tag
from .utils import (
    can_complete_job,
    can_modify_job,
    can_view_job,
    check_job_permission,
    format_bucket_list,
    format_job_list,
    format_job_view,
    get_account,
    get_bucket,
    get_job,
)


class BucketModelTests(TestCase):
    """Test Bucket model functionality."""
    
    def setUp(self):
        """Set up test buckets."""
        self.account = AccountDB.objects.create_user(
            username="TestUser",
            email="test@example.com",
            password="testpass123"
        )
        self.bucket1 = Bucket.objects.create(
            name="Bugs",
            description="Bug reports and fixes",
            created_by=self.account
        )
        self.bucket2 = Bucket.objects.create(
            name="Features",
            description="Feature requests",
            created_by=self.account
        )
    
    def test_bucket_creation(self):
        """Test basic bucket creation."""
        self.assertEqual(self.bucket1.name, "Bugs")
        self.assertEqual(self.bucket1.description, "Bug reports and fixes")
        self.assertFalse(self.bucket1.is_archived)
        self.assertEqual(self.bucket1.created_by, self.account)
    
    def test_bucket_str(self):
        """Test bucket string representation."""
        self.assertEqual(str(self.bucket1), "Bugs")
    
    def test_bucket_archived(self):
        """Test bucket archiving."""
        self.bucket1.is_archived = True
        self.bucket1.save()
        self.assertTrue(self.bucket1.is_archived)


class TagModelTests(TestCase):
    """Test Tag model functionality."""
    
    def test_tag_creation(self):
        """Test basic tag creation."""
        tag = Tag.objects.create(name="critical")
        self.assertEqual(tag.name, "critical")
    
    def test_tag_str(self):
        """Test tag string representation."""
        tag = Tag.objects.create(name="enhancement")
        self.assertEqual(str(tag), "enhancement")


class JobModelTests(TestCase):
    """Test Job model functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.account1 = AccountDB.objects.create_user(
            username="TestUser1",
            email="test1@example.com",
            password="testpass123"
        )
        self.account2 = AccountDB.objects.create_user(
            username="TestUser2",
            email="test2@example.com",
            password="testpass123"
        )
        self.bucket = Bucket.objects.create(
            name="Bugs",
            description="Bug reports",
            created_by=self.account1
        )
    
    def test_job_creation(self):
        """Test basic job creation."""
        job = Job.objects.create(
            bucket=self.bucket,
            title="Test Job",
            description="This is a test job.",
            creator=self.account1,
            status="OPEN"
        )
        self.assertEqual(job.title, "Test Job")
        self.assertEqual(job.creator, self.account1)
        self.assertEqual(job.bucket, self.bucket)
        self.assertEqual(job.status, "OPEN")
        self.assertFalse(job.completed)
    
    def test_sequence_number_auto_increment(self):
        """Test that sequence_number auto-increments per bucket."""
        job1 = Job.objects.create(
            bucket=self.bucket,
            title="Job 1",
            description="First job",
            creator=self.account1
        )
        job2 = Job.objects.create(
            bucket=self.bucket,
            title="Job 2",
            description="Second job",
            creator=self.account1
        )
        job3 = Job.objects.create(
            bucket=self.bucket,
            title="Job 3",
            description="Third job",
            creator=self.account1
        )
        
        self.assertEqual(job1.sequence_number, 1)
        self.assertEqual(job2.sequence_number, 2)
        self.assertEqual(job3.sequence_number, 3)
    
    def test_sequence_number_per_bucket(self):
        """Test that sequence_number is per-bucket."""
        bucket2 = Bucket.objects.create(
            name="Features",
            description="Feature requests",
            created_by=self.account1
        )
        
        job1_bucket1 = Job.objects.create(
            bucket=self.bucket,
            title="Bug 1",
            description="First bug",
            creator=self.account1
        )
        job1_bucket2 = Job.objects.create(
            bucket=bucket2,
            title="Feature 1",
            description="First feature",
            creator=self.account1
        )
        job2_bucket1 = Job.objects.create(
            bucket=self.bucket,
            title="Bug 2",
            description="Second bug",
            creator=self.account1
        )
        
        self.assertEqual(job1_bucket1.sequence_number, 1)
        self.assertEqual(job1_bucket2.sequence_number, 1)
        self.assertEqual(job2_bucket1.sequence_number, 2)
    
    def test_job_players_relationship(self):
        """Test job-players many-to-many relationship."""
        job = Job.objects.create(
            bucket=self.bucket,
            title="Assigned Job",
            description="Job with multiple players",
            creator=self.account1
        )
        
        job.players.add(self.account1)
        job.players.add(self.account2)
        
        self.assertEqual(job.players.count(), 2)
        self.assertIn(self.account1, job.players.all())
        self.assertIn(self.account2, job.players.all())
    
    def test_job_tags_relationship(self):
        """Test job-tags many-to-many relationship."""
        tag1 = Tag.objects.create(name="critical")
        tag2 = Tag.objects.create(name="enhancement")
        
        job = Job.objects.create(
            bucket=self.bucket,
            title="Tagged Job",
            description="Job with tags",
            creator=self.account1
        )
        
        job.tags.add(tag1)
        job.tags.add(tag2)
        
        self.assertEqual(job.tags.count(), 2)
        self.assertIn(tag1, job.tags.all())
        self.assertIn(tag2, job.tags.all())
    
    def test_job_str(self):
        """Test job string representation."""
        job = Job.objects.create(
            bucket=self.bucket,
            title="Test Job",
            description="Test description",
            creator=self.account1
        )
        self.assertEqual(str(job), "Job 1: Test Job")


class JobRaceConditionTests(TestCase):
    """Job sequence numbers must survive two creators reading the same max."""

    def setUp(self):
        """Set up test data."""
        self.account = AccountDB.objects.create_user(
            username="TestUser",
            email="test@example.com",
            password="testpass123"
        )
        self.bucket = Bucket.objects.create(
            name="Bugs",
            description="Test bucket",
            created_by=self.account
        )

    # F-097: two creators that read the same max collide on unique_together.
    # This replays that interleaving deterministically: the second create sees
    # the max as it was before the first create committed, and must retry.
    def test_stale_sequence_read_does_not_lose_job(self):
        Job.objects.create(
            bucket=self.bucket, title="Job 1", description="First", creator=self.account
        )
        real_aggregate = QuerySet.aggregate
        calls = []

        def stale_once(queryset, *args, **kwargs):
            if not calls:
                calls.append(True)
                return {"sequence_number__max": None}
            return real_aggregate(queryset, *args, **kwargs)

        with patch.object(QuerySet, "aggregate", stale_once), transaction.atomic():
            job = Job.objects.create(
                bucket=self.bucket, title="Job 2", description="Second", creator=self.account
            )
        self.assertEqual(job.sequence_number, 2)
        self.assertEqual(Job.objects.filter(bucket=self.bucket).count(), 2)


class JobConcurrentCreateTests(TransactionTestCase):
    """F-097: ten threads creating jobs in one bucket at once all succeed."""

    def setUp(self):
        self.account = AccountDB.objects.create_user(
            username="Racer", email="racer@example.com", password="testpass123"
        )
        self.bucket = Bucket.objects.create(name="Race", description="Race bucket")

    def test_concurrent_job_creation(self):
        num_threads = 10
        barrier = threading.Barrier(num_threads)

        def create(n):
            try:
                barrier.wait(timeout=10)
                return Job.objects.create(
                    bucket=self.bucket,
                    title=f"Job {n}",
                    description=f"Description {n}",
                    creator=self.account,
                ).sequence_number
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [pool.submit(create, n) for n in range(num_threads)]
            # .result() re-raises any exception from the thread, so a lost
            # job shows up as its IntegrityError/OperationalError.
            numbers = sorted(future.result() for future in futures)

        self.assertEqual(numbers, list(range(1, num_threads + 1)))
        self.assertEqual(Job.objects.filter(bucket=self.bucket).count(), num_threads)


class PriorityMigrationTests(TestCase):
    """R-4/R-15: jobs.0002 maps the old +hunt/staffed 'NORMAL' priority to MEDIUM."""

    def test_normalize_priority(self):
        from importlib import import_module

        from django.apps import apps

        account = create.create_account("Hunter", "hunter@example.com", "testpass123")
        bucket = Bucket.objects.create(name="Hunt Scenes", description="Hunts")
        job = Job.objects.create(bucket=bucket, title="Hunt", description="d", creator=account)
        Job.objects.filter(pk=job.pk).update(priority="NORMAL")  # as stored before PR 9

        import_module("jobs.migrations.0002_normalize_priority").normalize_priority(apps, None)

        job.refresh_from_db()
        self.assertEqual(job.priority, "MEDIUM")
        job.save()  # passes clean() again


class CommentModelTests(TestCase):
    """Test Comment model functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.account = AccountDB.objects.create_user(
            username="TestUser",
            email="test@example.com",
            password="testpass123"
        )
        self.bucket = Bucket.objects.create(
            name="Bugs",
            description="Test bucket",
            created_by=self.account
        )
        self.job = Job.objects.create(
            bucket=self.bucket,
            title="Test Job",
            description="Test description",
            creator=self.account
        )
    
    def test_comment_creation(self):
        """Test basic comment creation."""
        comment = Comment.objects.create(
            job=self.job,
            author=self.account,
            content="This is a comment.",
            public=False
        )
        
        self.assertEqual(comment.author, self.account)
        self.assertEqual(comment.job, self.job)
        self.assertEqual(comment.content, "This is a comment.")
        self.assertFalse(comment.public)
    
    def test_comment_public(self):
        """Test public comment creation."""
        comment = Comment.objects.create(
            job=self.job,
            author=self.account,
            content="Public comment",
            public=True
        )
        
        self.assertTrue(comment.public)
    
    def test_comment_relationship(self):
        """Test comment-job relationship."""
        comment1 = Comment.objects.create(
            job=self.job,
            author=self.account,
            content="Comment 1"
        )
        comment2 = Comment.objects.create(
            job=self.job,
            author=self.account,
            content="Comment 2"
        )
        
        comments = self.job.comments.all()
        self.assertEqual(comments.count(), 2)
        self.assertIn(comment1, comments)
        self.assertIn(comment2, comments)
    
    def test_comment_str(self):
        """Test comment string representation."""
        comment = Comment.objects.create(
            job=self.job,
            author=self.account,
            content="Test comment",
            public=True
        )
        self.assertIn("Public comment", str(comment))
        self.assertIn("TestUser", str(comment))


class UtilityFunctionTests(TestCase):
    """Test Jobs utility functions with real (typeclassed) accounts as callers."""

    def setUp(self):
        """Set up test data."""
        self.account1 = create.create_account("TestUser", "test@example.com", "testpass123")
        self.account2 = create.create_account("OtherUser", "other@example.com", "testpass123")
        self.admin_account = create.create_account(
            "AdminUser", "admin@example.com", "adminpass123", is_superuser=True
        )
        self.builder = create.create_account("BuilderUser", "builder@example.com", "testpass123")
        self.builder.permissions.add("Builder")

        self.bucket1 = Bucket.objects.create(
            name="Bugs", description="Bug reports", created_by=self.account1
        )
        self.bucket2 = Bucket.objects.create(
            name="Features", description="Feature requests", created_by=self.account1
        )

        self.job1 = Job.objects.create(
            bucket=self.bucket1,
            title="Test Job",
            description="Test description",
            creator=self.account1,
            status="OPEN",
        )

    def test_get_bucket_by_name(self):
        self.assertEqual(get_bucket(self.account1, "Bugs"), self.bucket1)

    def test_get_bucket_case_insensitive(self):
        self.assertEqual(get_bucket(self.account1, "BUGS"), self.bucket1)

    def test_get_bucket_not_found(self):
        self.assertIsNone(get_bucket(self.account1, "NonExistent"))

    def test_get_job_by_sequence_number(self):
        self.assertEqual(get_job(self.account1, 1), self.job1)

    def test_get_job_with_bucket(self):
        self.assertEqual(get_job(self.account1, 1, bucket=self.bucket1), self.job1)

    def test_get_job_by_bucket_ref(self):
        self.assertEqual(get_job(self.account1, "bugs/1"), self.job1)

    def test_get_job_not_found(self):
        self.assertIsNone(get_job(self.account1, 999))

    def test_get_job_bare_number_ambiguous_across_buckets(self):
        """F-055: job 1 with a job 1 in two buckets is refused, not a traceback."""
        feature = Job.objects.create(
            bucket=self.bucket2, title="Feature", description="d", creator=self.account1
        )
        with patch.object(self.account1, "msg") as msg:
            self.assertIsNone(get_job(self.account1, "1"))
        self.assertIn("ambiguous", msg.call_args[0][0])
        self.assertEqual(get_job(self.account1, "Features/1"), feature)

    def test_get_account_by_username(self):
        self.assertEqual(get_account(self.account1, "OtherUser"), self.account2)

    def test_get_account_case_insensitive(self):
        self.assertEqual(get_account(self.account1, "OTHERUSER"), self.account2)

    def test_get_account_not_found(self):
        self.assertIsNone(get_account(self.account1, "NonExistent"))

    def test_check_job_permission_creator(self):
        self.assertTrue(check_job_permission(self.account1, self.job1))

    def test_check_job_permission_assigned(self):
        self.job1.players.add(self.account2)
        self.assertTrue(check_job_permission(self.account2, self.job1))

    def test_check_job_permission_staff(self):
        self.assertTrue(check_job_permission(self.admin_account, self.job1))
        self.assertTrue(check_job_permission(self.builder, self.job1))

    def test_check_job_permission_denied(self):
        self.assertFalse(check_job_permission(self.account2, self.job1))

    def test_format_job_list_empty(self):
        self.assertEqual(format_job_list([], "All Open Jobs"), "There are no jobs.")

    def test_format_job_list_with_jobs(self):
        output = format_job_list([self.job1], "All Open Jobs")
        self.assertIn("Test Job", output)
        self.assertIn("Bugs", output)

    def test_format_job_list_shows_title(self):
        """A non-empty job list is headed by the title it was given."""
        output = format_job_list([self.job1], "All Open Jobs")
        self.assertIn("All Open Jobs", output)

    def test_format_bucket_list_empty(self):
        self.assertEqual(format_bucket_list([]), "No buckets found.")

    def test_format_bucket_list_with_buckets(self):
        output = format_bucket_list([self.bucket1, self.bucket2])
        self.assertIn("Bugs", output)
        self.assertIn("Features", output)

    def test_format_job_view(self):
        output = format_job_view(self.job1, self.account1)
        self.assertIn("Test Job", output)
        self.assertIn("Bugs/1", output)
        self.assertIn("TestUser", output)
        self.assertIn("OPEN", output)

    def test_format_job_view_hides_private_comments_from_players(self):
        """F-030: private comments are staff-only, except to their own author."""
        Comment.objects.create(
            job=self.job1, author=self.admin_account, content="STAFF ONLY NOTE", public=False
        )
        Comment.objects.create(
            job=self.job1, author=self.account1, content="my own note", public=False
        )
        Comment.objects.create(
            job=self.job1, author=self.admin_account, content="public reply", public=True
        )
        player_view = format_job_view(self.job1, self.account1)
        self.assertNotIn("STAFF ONLY NOTE", player_view)
        self.assertIn("my own note", player_view)
        self.assertIn("public reply", player_view)

        staff_view = format_job_view(self.job1, self.builder)
        self.assertIn("STAFF ONLY NOTE", staff_view)
        self.assertIn("my own note", staff_view)

    def test_can_view_job(self):
        """F-030: only staff, the creator and assignees can view a job."""
        self.assertTrue(can_view_job(self.account1, self.job1))
        self.assertTrue(can_view_job(self.builder, self.job1))
        self.assertTrue(can_view_job(self.admin_account, self.job1))
        self.assertFalse(can_view_job(self.account2, self.job1))
        self.job1.players.add(self.account2)
        self.assertTrue(can_view_job(self.account2, self.job1))

    def test_can_modify_job(self):
        self.assertTrue(can_modify_job(self.account1, self.job1))
        self.assertFalse(can_modify_job(self.account2, self.job1))

    def test_can_complete_job_creator(self):
        """The creator may withdraw their own job."""
        self.assertTrue(can_complete_job(self.account1, self.job1))

    def test_can_complete_job_assigned_player_cannot(self):
        """F-060: being added to a job doesn't let a player close it."""
        self.job1.players.add(self.account2)
        self.assertFalse(can_complete_job(self.account2, self.job1))

    def test_can_complete_job_staff(self):
        self.assertTrue(can_complete_job(self.admin_account, self.job1))
        self.assertTrue(can_complete_job(self.builder, self.job1))

    def test_can_complete_job_denied(self):
        self.assertFalse(can_complete_job(self.account2, self.job1))

    def test_job_rejects_unknown_priority(self):
        with self.assertRaises(ValidationError):
            Job.objects.create(
                bucket=self.bucket1,
                title="Bad",
                description="d",
                creator=self.account1,
                priority="NORMAL",
            )


class CommandTestBase(EvenniaCommandTest):
    """Base class for command tests using Evennia test helpers."""

    def call(self, cmdobj, input_args, msg=None, **kwargs):
        """Run the command and check that ``msg`` appears anywhere in its output.

        Evennia's own ``call`` only checks that the output *starts* with
        ``msg``. These tests name a fragment of the output instead, so match
        it as a substring.
        """
        output = super().call(cmdobj, input_args, **kwargs)
        if msg is not None:
            self.assertIn(msg, output)
        return output

    def setUp(self):
        """Set up test environment."""
        super().setUp()
        
        # Create test buckets
        self.bucket = Bucket.objects.create(
            name="Bugs",
            description="Bug reports",
            created_by=self.account
        )
        
        # Create test job
        self.job1 = Job.objects.create(
            bucket=self.bucket,
            title="Test Job",
            description="Test description",
            creator=self.account,
            status="OPEN"
        )


class CmdJobsTests(CommandTestBase):
    """Test CmdJobs command."""
    
    def test_list_all_jobs(self):
        """Test jobs lists all open jobs."""
        self.call(CmdJobs(), "", "Test Job")
    
    def test_list_bucket_jobs(self):
        """Test jobs <bucket> lists jobs in bucket."""
        output = self.call(CmdJobs(), "Bugs", "Test Job")
        self.assertIn("Bugs", output)
    
    def test_list_nonexistent_bucket(self):
        """Test jobs with non-existent bucket."""
        self.call(CmdJobs(), "NonExistent", "not found")


class CmdJobViewTests(CommandTestBase):
    """Test CmdJobView command."""
    
    def test_view_job(self):
        """Test job <id> views a job."""
        self.call(CmdJobView(), "1", "Test Job")
        self.call(CmdJobView(), "1", "Test description")
    
    def test_view_job_no_args(self):
        """Test job with no arguments."""
        self.call(CmdJobView(), "", "Usage:")
    
    def test_view_nonexistent_job(self):
        """Test job with non-existent id."""
        self.call(CmdJobView(), "999", "not found")


class CmdJobClaimTests(CommandTestBase):
    """Test CmdJobClaim command."""
    
    def test_claim_job(self):
        """Test job/claim claims a job."""
        self.call(CmdJobClaim(), "1", "You have claimed job Bugs/1")
        
        # Verify job was claimed
        self.job1.refresh_from_db()
        self.assertIn(self.account, self.job1.players.all())
    
    def test_claim_already_assigned(self):
        """Test claiming already assigned job."""
        self.job1.players.add(self.account)
        self.call(CmdJobClaim(), "1", "already assigned")


class CmdJobDoneTests(CommandTestBase):
    """Test CmdJobDone command."""
    
    def test_complete_job(self):
        """Test job/done completes a job."""
        self.job1.players.add(self.account)
        self.call(CmdJobDone(), "1", "marked as complete")
        
        # Verify job was completed
        self.job1.refresh_from_db()
        self.assertTrue(self.job1.completed)
        self.assertEqual(self.job1.status, "CLOSED")
    
    def test_complete_already_completed(self):
        """Test completing already completed job."""
        self.job1.completed = True
        self.job1.save()
        self.call(CmdJobDone(), "1", "already completed")


class CmdJobCommentTests(CommandTestBase):
    """Test CmdJobComment command."""
    
    def test_add_comment(self):
        """Test job/comment adds a private comment."""
        self.call(CmdJobComment(), "1 = This is a comment", "Private comment added")
        
        # Verify comment was created
        comment = Comment.objects.get(job=self.job1)
        self.assertEqual(comment.content, "This is a comment")
        self.assertFalse(comment.public)
    
    def test_add_comment_no_args(self):
        """Test job/comment with no arguments."""
        self.call(CmdJobComment(), "", "Usage:")


class CmdJobPublicTests(CommandTestBase):
    """Test CmdJobPublic command."""
    
    def test_add_public_comment(self):
        """Test job/public adds a public comment."""
        self.call(CmdJobPublic(), "1 = Public update", "Public comment added")
        
        # Verify comment was created
        comment = Comment.objects.get(job=self.job1)
        self.assertEqual(comment.content, "Public update")
        self.assertTrue(comment.public)


class CmdMyJobsTests(CommandTestBase):
    """Test CmdMyJobs command."""
    
    def test_list_my_jobs(self):
        """Test myjobs lists my created jobs."""
        self.call(CmdMyJobs(), "", "Test Job")


class CmdJobSubmitTests(CommandTestBase):
    """Test CmdJobSubmit command."""
    
    def test_create_job(self):
        """Test job/submit creates a job."""
        self.call(
            CmdJobSubmit(),
            "Bugs New Bug = Found a new bug",
            "Job Bugs/2 created"
        )
        
        # Verify job was created
        job = Job.objects.get(bucket=self.bucket, sequence_number=2)
        self.assertEqual(job.title, "New Bug")
        self.assertEqual(job.description, "Found a new bug")
    
    def test_create_job_no_args(self):
        """Test job/submit with no arguments."""
        self.call(CmdJobSubmit(), "", "Usage:")


class CmdJobAssignTests(CommandTestBase):
    """Test CmdJobAssign command (admin)."""
    
    def test_assign_job(self):
        """Test job/assign assigns job to player."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        self.call(CmdJobAssign(), "1 = TestAccount", "Job Bugs/1 assigned")


class CmdJobReopenTests(CommandTestBase):
    """Test CmdJobReopen command (admin)."""
    
    def test_reopen_job(self):
        """Test job/reopen reopens completed job."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        # Complete the job first
        self.job1.completed = True
        self.job1.status = "CLOSED"
        self.job1.save()
        
        self.call(CmdJobReopen(), "1", "has been reopened")
        
        # Verify job was reopened
        self.job1.refresh_from_db()
        self.assertFalse(self.job1.completed)
        self.assertEqual(self.job1.status, "OPEN")


class CmdJobDeleteTests(CommandTestBase):
    """Test CmdJobDelete command (admin)."""
    
    def test_delete_job(self):
        """Test job/delete deletes a job."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        self.call(CmdJobDelete(), "1", "has been deleted")
        
        # Verify job was deleted
        self.assertFalse(Job.objects.filter(pk=self.job1.pk).exists())


class CmdBucketsTests(CommandTestBase):
    """Test CmdBuckets command (admin)."""
    
    def test_list_buckets(self):
        """Test buckets lists all buckets."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        self.call(CmdBuckets(), "", "Bugs")


class CmdBucketCreateTests(CommandTestBase):
    """Test CmdBucketCreate command (admin)."""
    
    def test_create_bucket(self):
        """Test bucket/create creates a bucket."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        self.call(
            CmdBucketCreate(),
            "Features = Feature requests",
            "Bucket 'Features' created"
        )
        
        # Verify bucket was created
        bucket = Bucket.objects.get(name="Features")
        self.assertEqual(bucket.description, "Feature requests")


class CmdBucketViewTests(CommandTestBase):
    """Test CmdBucketView command (admin)."""
    
    def test_view_bucket(self):
        """Test bucket <name> views bucket details."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        self.call(CmdBucketView(), "Bugs", "Bucket: Bugs")
        self.call(CmdBucketView(), "Bugs", "Bug reports")


class CmdBucketDeleteTests(CommandTestBase):
    """Test CmdBucketDelete command (admin)."""
    
    def test_delete_empty_bucket(self):
        """Test bucket/delete deletes empty bucket."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        # Create empty bucket
        empty_bucket = Bucket.objects.create(
            name="Empty",
            description="Empty bucket",
            created_by=self.account
        )
        
        self.call(CmdBucketDelete(), "Empty", "has been deleted")
        
        # Verify bucket was deleted
        self.assertFalse(Bucket.objects.filter(name="Empty").exists())
    
    def test_delete_bucket_with_jobs(self):
        """Test bucket/delete prevents deleting bucket with jobs."""
        # Make char1 a builder
        self.char1.permissions.add("Builder")
        
        self.call(CmdBucketDelete(), "Bugs", "contains jobs")


class JobAuthorizationCommandTests(CommandTestBase):
    """F-030/F-055/F-060: two players (Alice, Bob) and one Builder."""

    def _puppet(self, name, *perms):
        account = create.create_account(name, email=f"{name}@example.com", password="pw123456")
        for perm in perms:
            account.permissions.add(perm)
        char = create.create_object(
            settings.BASE_CHARACTER_TYPECLASS, key=name, location=self.room1, home=self.room1
        )
        char.account = account
        return account, char

    def setUp(self):
        super().setUp()
        self.alice_account, self.alice = self._puppet("Alice")
        self.bob_account, self.bob = self._puppet("Bob")
        self.builder_account, self.builder = self._puppet("Wren", "Builder")
        self.approval = Bucket.objects.create(name="Approval", description="Approvals")
        self.alice_job = Job.objects.create(
            bucket=self.approval,
            title="Alice approval",
            description="Please approve Alice",
            creator=self.alice_account,
        )
        Comment.objects.create(
            job=self.alice_job,
            author=self.builder_account,
            content="STAFF ONLY NOTE",
            public=False,
        )

    def test_other_player_cannot_view_job(self):
        # A job Bob can't see is reported exactly like a missing one.
        output = self.call(CmdJobView(), "Approval/1", caller=self.bob)
        self.assertIn("Job Approval/1 not found", output)
        self.assertEqual(output, self.call(CmdJobView(), "Approval/99", caller=self.bob).replace("99", "1"))
        self.assertNotIn("STAFF ONLY NOTE", output)
        self.assertNotIn("Please approve Alice", output)

    def test_creator_sees_job_but_not_private_comment(self):
        output = self.call(CmdJobView(), "Approval/1", caller=self.alice)
        self.assertIn("Please approve Alice", output)
        self.assertNotIn("STAFF ONLY NOTE", output)

    def test_builder_sees_private_comment(self):
        output = self.call(CmdJobView(), "Approval/1", caller=self.builder)
        self.assertIn("STAFF ONLY NOTE", output)

    def test_other_player_cannot_claim_job(self):
        self.assertFalse(CmdJobClaim().access(self.bob, "cmd"))
        self.assertTrue(CmdJobClaim().access(self.builder, "cmd"))
        self.call(CmdJobClaim(), "Approval/1", "You have claimed", caller=self.builder)
        self.assertIn(self.builder_account, self.alice_job.players.all())

    def test_player_claim_falls_through_to_a_refusal(self):
        """With job/claim locked, a player's "job/claim X" reaches `job` as a switch."""
        self.alice_job.players.clear()
        output = self.call(CmdJobView(), "/claim Approval/1", caller=self.alice)
        self.assertIn("staff-only switch: /claim", output)
        self.assertNotIn("Please approve Alice", output)
        self.assertFalse(self.alice_job.players.exists())
        output = self.call(CmdJobs(), "/claim", caller=self.alice)
        self.assertIn("staff-only switch: /claim", output)

    def test_other_player_cannot_close_job(self):
        output = self.call(CmdJobDone(), "Approval/1", caller=self.bob)
        self.assertIn("not found", output)
        self.alice_job.refresh_from_db()
        self.assertEqual(self.alice_job.status, "OPEN")

    def test_creator_can_withdraw_own_job(self):
        self.call(CmdJobDone(), "Approval/1", "Job Approval/1", caller=self.alice)
        self.alice_job.refresh_from_db()
        self.assertEqual(self.alice_job.status, "CLOSED")

    def test_builder_can_close_job(self):
        self.call(CmdJobDone(), "Approval/1", "Job Approval/1", caller=self.builder)
        self.alice_job.refresh_from_db()
        self.assertEqual(self.alice_job.status, "CLOSED")

    def test_jobs_list_shows_only_own_jobs_to_players(self):
        bob_output = self.call(CmdJobs(), "", caller=self.bob)
        self.assertNotIn("Alice approval", bob_output)
        bob_bucket_output = self.call(CmdJobs(), "Approval", caller=self.bob)
        self.assertNotIn("Alice approval", bob_bucket_output)
        self.assertIn("Alice approval", self.call(CmdJobs(), "Approval", caller=self.alice))
        alice_output = self.call(CmdJobs(), "", caller=self.alice)
        self.assertIn("Alice approval", alice_output)
        builder_output = self.call(CmdJobs(), "", caller=self.builder)
        self.assertIn("Alice approval", builder_output)
        self.assertIn("Test Job", builder_output)

    def test_bare_number_with_two_buckets_is_ambiguous(self):
        """Bugs/1 and Approval/1 both exist."""
        output = self.call(CmdJobView(), "1", caller=self.builder)
        self.assertIn("ambiguous", output)

    def test_bare_number_resolves_among_visible_jobs_only(self):
        """Bob's `job 1` never names other players' jobs (R-1/R-8)."""
        output = self.call(CmdJobView(), "1", caller=self.bob)
        self.assertIn("not found", output)
        self.assertNotIn("Approval", output)
        self.assertNotIn("Bugs", output)
        # Alice can see only Approval/1, so her bare `1` is not ambiguous.
        output = self.call(CmdJobView(), "1", caller=self.alice)
        self.assertIn("Please approve Alice", output)
        bob_job = Job.objects.create(
            bucket=Bucket.objects.create(name="Plots", description="Plots"),
            title="Bob plot",
            description="Bob's plot request",
            creator=self.bob_account,
        )
        self.assertEqual(bob_job.sequence_number, 1)
        self.assertIn("Bob's plot request", self.call(CmdJobView(), "1", caller=self.bob))

    def test_myjobs_defaults_to_open(self):
        self.alice_job.status = "CLOSED"
        self.alice_job.save()
        self.assertNotIn("Alice approval", self.call(CmdMyJobs(), "", caller=self.alice))
        self.assertIn("Alice approval", self.call(CmdMyJobs(), "all", caller=self.alice))
