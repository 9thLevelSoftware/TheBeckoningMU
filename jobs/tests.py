"""
Comprehensive Jobs system tests.

Tests models, utilities, and commands following BBS test patterns.
"""

import threading
from unittest.mock import Mock
from django.test import TestCase, TransactionTestCase
from evennia.accounts.models import AccountDB
from evennia.utils.test_resources import BaseEvenniaTest
from .models import Job, Bucket, Comment, Tag
from .utils import (
    get_job, get_bucket, get_account, check_job_permission,
    format_job_view, format_job_list, format_bucket_list,
    can_view_job, can_modify_job, can_complete_job
)
from .commands import (
    CmdJobs, CmdJobView, CmdJobClaim, CmdJobDone, CmdJobComment, CmdJobPublic,
    CmdMyJobs, CmdJobSubmit, CmdJobCreate, CmdJobAssign, CmdJobReopen,
    CmdJobDelete, CmdBuckets, CmdBucketCreate, CmdBucketView, CmdBucketDelete
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


class JobRaceConditionTests(TransactionTestCase):
    """Test Job race condition protection using TransactionTestCase."""
    
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
    
    def create_job(self, job_num):
        """Helper to create a job (for threading)."""
        Job.objects.create(
            bucket=self.bucket,
            title=f"Job {job_num}",
            description=f"Description {job_num}",
            creator=self.account
        )
    
    def test_concurrent_job_creation(self):
        """Test that concurrent jobs get unique sequence numbers."""
        threads = []
        num_threads = 10
        
        # Create 10 jobs concurrently
        for i in range(num_threads):
            thread = threading.Thread(target=self.create_job, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all jobs were created with unique sequence numbers
        jobs = Job.objects.filter(bucket=self.bucket).order_by('sequence_number')
        self.assertEqual(jobs.count(), num_threads)
        
        # Check sequence numbers are 1-10 with no duplicates
        sequence_numbers = [job.sequence_number for job in jobs]
        self.assertEqual(sequence_numbers, list(range(1, num_threads + 1)))


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
    """Test Jobs utility functions."""
    
    def setUp(self):
        """Set up test data."""
        self.account1 = AccountDB.objects.create_user(
            username="TestUser",
            email="test@example.com",
            password="testpass123"
        )
        self.account2 = AccountDB.objects.create_user(
            username="OtherUser",
            email="other@example.com",
            password="testpass123"
        )
        self.admin_account = AccountDB.objects.create_superuser(
            username="AdminUser",
            email="admin@example.com",
            password="adminpass123"
        )
        
        self.bucket1 = Bucket.objects.create(
            name="Bugs",
            description="Bug reports",
            created_by=self.account1
        )
        self.bucket2 = Bucket.objects.create(
            name="Features",
            description="Feature requests",
            created_by=self.account1
        )
        
        self.job1 = Job.objects.create(
            bucket=self.bucket1,
            title="Test Job",
            description="Test description",
            creator=self.account1,
            status="OPEN"
        )
        self.job1.players.add(self.account1)
    
    def _create_mock_caller(self, account, has_builder_perm=False):
        """Create a mock caller (character) with account."""
        caller = Mock()
        caller.account = account
        caller.msg = Mock()
        caller.check_permstring = Mock(return_value=has_builder_perm)
        return caller
    
    def test_get_bucket_by_name(self):
        """Test get_bucket by name."""
        caller = self._create_mock_caller(self.account1)
        bucket = get_bucket(caller, "Bugs")
        self.assertEqual(bucket, self.bucket1)
    
    def test_get_bucket_case_insensitive(self):
        """Test get_bucket is case-insensitive."""
        caller = self._create_mock_caller(self.account1)
        bucket = get_bucket(caller, "BUGS")
        self.assertEqual(bucket, self.bucket1)
    
    def test_get_bucket_not_found(self):
        """Test get_bucket returns None for non-existent bucket."""
        caller = self._create_mock_caller(self.account1)
        bucket = get_bucket(caller, "NonExistent")
        self.assertIsNone(bucket)
        caller.msg.assert_called()
    
    def test_get_job_by_sequence_number(self):
        """Test get_job by sequence number."""
        caller = self._create_mock_caller(self.account1)
        job = get_job(caller, 1)
        self.assertEqual(job, self.job1)
    
    def test_get_job_with_bucket(self):
        """Test get_job with specific bucket."""
        caller = self._create_mock_caller(self.account1)
        job = get_job(caller, 1, bucket=self.bucket1)
        self.assertEqual(job, self.job1)
    
    def test_get_job_not_found(self):
        """Test get_job returns None for non-existent job."""
        caller = self._create_mock_caller(self.account1)
        job = get_job(caller, 999)
        self.assertIsNone(job)
        caller.msg.assert_called()
    
    def test_get_account_by_username(self):
        """Test get_account by username."""
        caller = self._create_mock_caller(self.account1)
        account = get_account(caller, "OtherUser")
        self.assertEqual(account, self.account2)
    
    def test_get_account_case_insensitive(self):
        """Test get_account is case-insensitive."""
        caller = self._create_mock_caller(self.account1)
        account = get_account(caller, "OTHERUSER")
        self.assertEqual(account, self.account2)
    
    def test_get_account_not_found(self):
        """Test get_account returns None for non-existent account."""
        caller = self._create_mock_caller(self.account1)
        account = get_account(caller, "NonExistent")
        self.assertIsNone(account)
        caller.msg.assert_called()
    
    def test_check_job_permission_creator(self):
        """Test check_job_permission for job creator."""
        caller = self._create_mock_caller(self.account1)
        self.assertTrue(check_job_permission(caller, self.job1))
    
    def test_check_job_permission_assigned(self):
        """Test check_job_permission for assigned player."""
        caller = self._create_mock_caller(self.account1)
        self.assertTrue(check_job_permission(caller, self.job1))
    
    def test_check_job_permission_admin(self):
        """Test check_job_permission for admin."""
        caller = self._create_mock_caller(self.admin_account, has_builder_perm=True)
        self.assertTrue(check_job_permission(caller, self.job1))
    
    def test_check_job_permission_denied(self):
        """Test check_job_permission denies unrelated user."""
        caller = self._create_mock_caller(self.account2)
        self.assertFalse(check_job_permission(caller, self.job1))
    
    def test_format_job_list_empty(self):
        """Test format_job_list with no jobs."""
        output = format_job_list([], "All Open Jobs")
        self.assertEqual(output, "There are no jobs.")
    
    def test_format_job_list_with_jobs(self):
        """Test format_job_list with jobs."""
        output = format_job_list([self.job1], "All Open Jobs")
        self.assertIn("All Open Jobs", output)
        self.assertIn("Test Job", output)
        self.assertIn("Bugs", output)
    
    def test_format_bucket_list_empty(self):
        """Test format_bucket_list with no buckets."""
        output = format_bucket_list([])
        self.assertEqual(output, "No buckets found.")
    
    def test_format_bucket_list_with_buckets(self):
        """Test format_bucket_list with buckets."""
        output = format_bucket_list([self.bucket1, self.bucket2])
        self.assertIn("Bugs", output)
        self.assertIn("Features", output)
    
    def test_format_job_view(self):
        """Test format_job_view."""
        output = format_job_view(self.job1)
        self.assertIn("Test Job", output)
        self.assertIn("Bugs", output)
        self.assertIn("TestUser", output)
        self.assertIn("OPEN", output)
    
    def test_can_view_job(self):
        """Test can_view_job (currently allows all)."""
        caller = self._create_mock_caller(self.account2)
        self.assertTrue(can_view_job(caller, self.job1))
    
    def test_can_modify_job(self):
        """Test can_modify_job."""
        caller = self._create_mock_caller(self.account1)
        self.assertTrue(can_modify_job(caller, self.job1))
        
        other_caller = self._create_mock_caller(self.account2)
        self.assertFalse(can_modify_job(other_caller, self.job1))
    
    def test_can_complete_job_creator(self):
        """Test can_complete_job for creator."""
        caller = self._create_mock_caller(self.account1)
        self.assertTrue(can_complete_job(caller, self.job1))
    
    def test_can_complete_job_assigned(self):
        """Test can_complete_job for assigned player."""
        caller = self._create_mock_caller(self.account1)
        self.assertTrue(can_complete_job(caller, self.job1))
    
    def test_can_complete_job_admin(self):
        """Test can_complete_job for admin."""
        caller = self._create_mock_caller(self.admin_account, has_builder_perm=True)
        self.assertTrue(can_complete_job(caller, self.job1))
    
    def test_can_complete_job_denied(self):
        """Test can_complete_job denies unrelated user."""
        caller = self._create_mock_caller(self.account2)
        self.assertFalse(can_complete_job(caller, self.job1))


class CommandTestBase(BaseEvenniaTest):
    """Base class for command tests using Evennia test helpers."""
    
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
        self.call(CmdJobs(), "", "All Open Jobs")
        self.call(CmdJobs(), "", "Test Job")
    
    def test_list_bucket_jobs(self):
        """Test jobs <bucket> lists jobs in bucket."""
        self.call(CmdJobs(), "Bugs", "Open Jobs in Bugs")
    
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
        self.call(CmdJobClaim(), "1", "You have claimed job #1")
        
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
        self.call(CmdMyJobs(), "", "My Jobs")
        self.call(CmdMyJobs(), "", "Test Job")


class CmdJobSubmitTests(CommandTestBase):
    """Test CmdJobSubmit command."""
    
    def test_create_job(self):
        """Test job/submit creates a job."""
        self.call(
            CmdJobSubmit(),
            "Bugs New Bug = Found a new bug",
            "Job #2 created"
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
        
        self.call(CmdJobAssign(), "1 = TestAccount", "Job #1 assigned")


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
        
        self.call(CmdBuckets(), "", "Job Buckets")
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
