"""
Jobs commands - focused, single-responsibility command classes.

Provides player-facing and admin commands for the Jobs system.
"""

from evennia import default_cmds
from evennia.utils import class_from_module
from .models import Job, Bucket, Comment
from evennia.accounts.models import AccountDB
from django.conf import settings
from django.db import Error as DbError
from . import utils

COMMAND_DEFAULT_CLASS = class_from_module(settings.COMMAND_DEFAULT_CLASS)


# =============================================================================
# Player-Facing Commands (Open permissions)
# =============================================================================

class CmdJobs(COMMAND_DEFAULT_CLASS):
    """
    List open jobs you can see.

    Usage:
      jobs                    - List open jobs
      +job/list               - Same as above (standard syntax)
      jobs <bucket_name>      - List open jobs in a specific bucket

    Staff see every job. Players see the jobs they created or are
    assigned to.
    
    Examples:
      jobs
      +job/list
      jobs Bugs
    """
    
    key = "jobs"
    aliases = ["+jobs", "+job/list"]
    locks = "cmd:all()"
    help_category = "Jobs"
    
    def func(self):
        if self.args:
            # List jobs in specific bucket
            bucket = utils.get_bucket(self.caller, self.args.strip())
            if not bucket:
                return
            
            jobs = utils.jobs_visible_to(self.caller, bucket.jobs.filter(status="OPEN"))
            output = utils.format_job_list(jobs, f"Open Jobs in {bucket.name}")
        else:
            # List all open jobs
            jobs = utils.jobs_visible_to(self.caller, Job.objects.filter(status="OPEN"))
            output = utils.format_job_list(jobs, "All Open Jobs")
        
        self.caller.msg(output)


class CmdJobView(COMMAND_DEFAULT_CLASS):
    """
    View details of a specific job.
    
    Usage:
      job <bucket>/<number>
      job <number>            - When only one bucket has that number
      +job/view <bucket>/<number>

    Job numbers are per bucket, so "job 1" is ambiguous once two buckets
    each have a job 1.

    Examples:
      job Bugs/5
      +job/view Approval/42
    """
    
    key = "job"
    aliases = ["+job", "+job/view"]
    locks = "cmd:all()"
    help_category = "Jobs"
    
    def func(self):
        if not self.args:
            self.caller.msg("Usage: job <bucket>/<number>")
            return
        
        job = utils.get_job(self.caller, self.args.strip())
        if not job:
            return
        
        if not utils.can_view_job(self.caller, job):
            self.caller.msg("You don't have permission to view this job.")
            return
        
        output = utils.format_job_view(job, self.caller)
        self.caller.msg(output)


class CmdJobClaim(COMMAND_DEFAULT_CLASS):
    """
    Claim an unassigned job (staff).

    Usage:
      job/claim <bucket>/<number>

    Examples:
      job/claim Bugs/5
    """

    key = "job/claim"
    aliases = ["+job/claim"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args:
            self.caller.msg("Usage: job/claim <bucket>/<number>")
            return
        
        job = utils.get_job(self.caller, self.args.strip())
        if not job:
            return
        
        if job.status != "OPEN":
            self.caller.msg("This job is not available for claiming.")
            return
        
        if job.players.exists():
            self.caller.msg("This job is already assigned to someone.")
            return
        
        # Claim the job
        job.players.add(self.caller.account)
        job.save()
        
        self.caller.msg(f"You have claimed job {job.ref}: {job.title}")


class CmdJobDone(COMMAND_DEFAULT_CLASS):
    """
    Close a job.

    Usage:
      job/done <bucket>/<number>
      +job/complete <bucket>/<number>

    Staff close jobs. A player may close (withdraw) a job they created.

    Examples:
      job/done Bugs/5
      +job/complete Approval/42
    """
    
    key = "job/done"
    aliases = ["+job/complete", "+job/done"]
    locks = "cmd:all()"
    help_category = "Jobs"
    
    def func(self):
        if not self.args:
            self.caller.msg("Usage: job/done <bucket>/<number>")
            return
        
        job = utils.get_job(self.caller, self.args.strip())
        if not job:
            return
        
        if not utils.can_complete_job(self.caller, job):
            self.caller.msg("You don't have permission to complete this job.")
            return
        
        if job.completed:
            self.caller.msg("This job is already completed.")
            return
        
        # Complete the job
        job.completed = True
        job.status = "CLOSED"
        job.save()
        
        self.caller.msg(f"Job {job.ref}: {job.title} has been marked as complete.")


class CmdJobComment(COMMAND_DEFAULT_CLASS):
    """
    Add a private comment to a job.

    Usage:
      job/comment <bucket>/<number> = <comment>

    Private comments are shown to staff and to the comment's author only.

    Examples:
      job/comment Bugs/5 = Working on this now
      job/comment Bugs/42 = Need more information about the bug
    """
    
    key = "job/comment"
    aliases = ["+job/comment", "+job/add"]
    locks = "cmd:all()"
    help_category = "Jobs"
    
    def func(self):
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: job/comment <bucket>/<number> = <comment>")
            return
        
        try:
            job_id, comment_text = self.args.split("=", 1)
        except ValueError:
            self.caller.msg("Usage: job/comment <bucket>/<number> = <comment>")
            return
        
        job = utils.get_job(self.caller, job_id.strip())
        if not job:
            return
        
        if not utils.check_job_permission(self.caller, job):
            self.caller.msg("You don't have permission to comment on this job.")
            return
        
        # Add the comment
        try:
            comment = Comment.objects.create(
                job=job,
                author=self.caller.account,
                content=comment_text.strip(),
                public=False
            )
            self.caller.msg(f"Private comment added to job {job.ref}.")
        except DbError as e:
            self.caller.msg(f"A database error occurred while adding the comment: {e}")


class CmdJobPublic(COMMAND_DEFAULT_CLASS):
    """
    Add a public comment to a job.
    
    Usage:
      job/public <bucket>/<number> = <comment>

    Public comments are shown to everyone who can see the job.

    Examples:
      job/public Bugs/5 = This issue has been resolved
      job/public Bugs/42 = Update: Still investigating
    """
    
    key = "job/public"
    aliases = ["+job/public"]
    locks = "cmd:all()"
    help_category = "Jobs"
    
    def func(self):
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: job/public <bucket>/<number> = <comment>")
            return
        
        try:
            job_id, comment_text = self.args.split("=", 1)
        except ValueError:
            self.caller.msg("Usage: job/public <bucket>/<number> = <comment>")
            return
        
        job = utils.get_job(self.caller, job_id.strip())
        if not job:
            return
        
        if not utils.check_job_permission(self.caller, job):
            self.caller.msg("You don't have permission to comment on this job.")
            return
        
        # Add the public comment
        try:
            comment = Comment.objects.create(
                job=job,
                author=self.caller.account,
                content=comment_text.strip(),
                public=True
            )
            self.caller.msg(f"Public comment added to job {job.ref}.")
        except DbError as e:
            self.caller.msg(f"A database error occurred while adding the comment: {e}")


# =============================================================================
# "My Jobs" Player Commands
# =============================================================================

class CmdMyJobs(COMMAND_DEFAULT_CLASS):
    """
    List the jobs you have created.

    Usage:
      myjobs          - Your open jobs
      myjobs all      - Your jobs, including closed ones

    Examples:
      myjobs
    """
    
    key = "myjobs"
    aliases = ["+myjobs", "+job/mine"]
    locks = "cmd:all()"
    help_category = "Jobs"
    
    def func(self):
        jobs = Job.objects.filter(creator=utils.account_of(self.caller))
        if self.args.strip().lower() != "all":
            jobs = jobs.filter(status="OPEN")
        jobs = jobs.select_related("bucket").prefetch_related("players")
        output = utils.format_job_list(jobs, "My Jobs")
        self.caller.msg(output)


class CmdJobSubmit(COMMAND_DEFAULT_CLASS):
    """
    Submit a new job.

    Usage:
      job/submit <bucket_name> <title> = <description>

    Examples:
      job/submit Bugs Character sheet not saving = My character sheet keeps resetting
      job/submit Features Add new command = Would like a +time command
    """

    key = "job/submit"
    aliases = ["+job/submit"]
    locks = "cmd:all()"
    help_category = "Jobs"

    def func(self):
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: job/submit <bucket_name> <title> = <description>")
            return
        
        try:
            bucket_and_title, description = self.args.split("=", 1)
            parts = bucket_and_title.strip().split(" ", 1)
            if len(parts) < 2:
                self.caller.msg("Usage: job/submit <bucket_name> <title> = <description>")
                return
            bucket_name, title = parts
        except ValueError:
            self.caller.msg("Usage: job/submit <bucket_name> <title> = <description>")
            return
        
        bucket = utils.get_bucket(self.caller, bucket_name.strip())
        if not bucket:
            return
        
        # Create the job
        try:
            job = Job.objects.create(
                bucket=bucket,
                title=title.strip(),
                description=description.strip(),
                creator=self.caller.account,
                status="OPEN"
            )
            self.caller.msg(f"Job {job.ref} created: {job.title}")
        except DbError as e:
            self.caller.msg(f"A database error occurred while creating the job: {e}")


# =============================================================================
# Admin Job Commands (Builder+ permissions)
# =============================================================================

class CmdJobCreate(COMMAND_DEFAULT_CLASS):
    """
    Create a new job in any bucket (admin).
    
    Usage:
      job/create <bucket_name> <title> = <description>
    
    Examples:
      job/create Bugs Server crash = Investigating server stability issues
    """
    
    key = "job/create"
    aliases = ["+job/admin/create"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: job/create <bucket_name> <title> = <description>")
            return
        
        try:
            bucket_and_title, description = self.args.split("=", 1)
            parts = bucket_and_title.strip().split(" ", 1)
            if len(parts) < 2:
                self.caller.msg("Usage: job/create <bucket_name> <title> = <description>")
                return
            bucket_name, title = parts
        except ValueError:
            self.caller.msg("Usage: job/create <bucket_name> <title> = <description>")
            return
        
        bucket = utils.get_bucket(self.caller, bucket_name.strip())
        if not bucket:
            return
        
        # Create the job
        try:
            job = Job.objects.create(
                bucket=bucket,
                title=title.strip(),
                description=description.strip(),
                creator=self.caller.account,
                status="OPEN"
            )
            self.caller.msg(f"Job {job.ref} created: {job.title}")
        except DbError as e:
            self.caller.msg(f"A database error occurred while creating the job: {e}")


class CmdJobAssign(COMMAND_DEFAULT_CLASS):
    """
    Assign a job to a player (admin).
    
    Usage:
      job/assign <bucket>/<number> = <player_name>

    Examples:
      job/assign Bugs/5 = Alice
      job/assign Bugs/42 = Bob
    """
    
    key = "job/assign"
    aliases = ["+job/assign"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: job/assign <bucket>/<number> = <player_name>")
            return
        
        try:
            job_id, player_name = self.args.split("=", 1)
        except ValueError:
            self.caller.msg("Usage: job/assign <bucket>/<number> = <player_name>")
            return
        
        job = utils.get_job(self.caller, job_id.strip())
        if not job:
            return
        
        account = utils.get_account(self.caller, player_name.strip())
        if not account:
            return
        
        # Assign the job
        job.players.add(account)
        job.save()
        
        self.caller.msg(f"Job {job.ref} assigned to {account.username}.")


class CmdJobReopen(COMMAND_DEFAULT_CLASS):
    """
    Reopen a completed job (admin).
    
    Usage:
      job/reopen <bucket>/<number>

    Examples:
      job/reopen Bugs/5
    """
    
    key = "job/reopen"
    aliases = ["+job/reopen"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args:
            self.caller.msg("Usage: job/reopen <bucket>/<number>")
            return
        
        job = utils.get_job(self.caller, self.args.strip())
        if not job:
            return
        
        if not job.completed:
            self.caller.msg("This job is not completed.")
            return
        
        # Reopen the job
        job.completed = False
        job.status = "OPEN"
        job.save()
        
        self.caller.msg(f"Job {job.ref}: {job.title} has been reopened.")


class CmdJobDelete(COMMAND_DEFAULT_CLASS):
    """
    Delete a job (admin).
    
    Usage:
      job/delete <bucket>/<number>

    Examples:
      job/delete Bugs/5
    """
    
    key = "job/delete"
    aliases = ["+job/delete"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args:
            self.caller.msg("Usage: job/delete <bucket>/<number>")
            return
        
        job = utils.get_job(self.caller, self.args.strip())
        if not job:
            return
        
        job_title = job.title
        job_ref = job.ref
        job.delete()

        self.caller.msg(f"Job {job_ref}: {job_title} has been deleted.")


# =============================================================================
# Bucket Management Commands (Admin only)
# =============================================================================

class CmdBuckets(COMMAND_DEFAULT_CLASS):
    """
    List all job buckets.
    
    Usage:
      buckets
    
    Examples:
      buckets
    """
    
    key = "buckets"
    aliases = ["+buckets"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        buckets = Bucket.objects.all()
        output = utils.format_bucket_list(buckets)
        self.caller.msg(output)


class CmdBucketCreate(COMMAND_DEFAULT_CLASS):
    """
    Create a new job bucket (admin).
    
    Usage:
      bucket/create <name> = <description>
    
    Examples:
      bucket/create Features = Feature requests from players
      bucket/create Bugs = Bug reports and fixes
    """
    
    key = "bucket/create"
    aliases = ["+bucket/create"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: bucket/create <name> = <description>")
            return
        
        try:
            name, description = self.args.split("=", 1)
        except ValueError:
            self.caller.msg("Usage: bucket/create <name> = <description>")
            return
        
        name = name.strip()
        description = description.strip()
        
        # Check if bucket already exists
        if Bucket.objects.filter(name__iexact=name).exists():
            self.caller.msg(f"Bucket '{name}' already exists.")
            return
        
        # Create the bucket
        try:
            bucket = Bucket.objects.create(
                name=name,
                description=description,
                created_by=self.caller.account
            )
            self.caller.msg(f"Bucket '{bucket.name}' created.")
        except DbError as e:
            self.caller.msg(f"A database error occurred while creating the bucket: {e}")


class CmdBucketView(COMMAND_DEFAULT_CLASS):
    """
    View details of a specific bucket.
    
    Usage:
      bucket <bucket_name>
    
    Examples:
      bucket Bugs
      bucket Features
    """
    
    key = "bucket"
    aliases = ["+bucket"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args:
            self.caller.msg("Usage: bucket <bucket_name>")
            return
        
        bucket = utils.get_bucket(self.caller, self.args.strip())
        if not bucket:
            return
        
        # Show bucket details and its jobs
        output = f"|wBucket: {bucket.name}|n\n"
        output += f"|wDescription:|n {bucket.description}\n"
        
        if bucket.created_by:
            output += f"|wCreated by:|n {bucket.created_by.username}\n\n"
        else:
            output += f"|wCreated by:|n System\n\n"
        
        jobs = bucket.jobs.select_related("bucket").prefetch_related("players")
        job_list = utils.format_job_list(jobs, f"Jobs in {bucket.name}")
        output += job_list
        
        self.caller.msg(output)


class CmdBucketDelete(COMMAND_DEFAULT_CLASS):
    """
    Delete a job bucket (admin).
    
    Usage:
      bucket/delete <bucket_name>
    
    Examples:
      bucket/delete OldBucket
    """
    
    key = "bucket/delete"
    aliases = ["+bucket/delete"]
    locks = "cmd:perm(Builder)"
    help_category = "Jobs"
    
    def func(self):
        if not self.args:
            self.caller.msg("Usage: bucket/delete <bucket_name>")
            return
        
        bucket = utils.get_bucket(self.caller, self.args.strip())
        if not bucket:
            return
        
        # Check if bucket has jobs
        if bucket.jobs.exists():
            self.caller.msg(f"Bucket '{bucket.name}' contains jobs and cannot be deleted.")
            return
        
        bucket_name = bucket.name
        bucket.delete()
        
        self.caller.msg(f"Bucket '{bucket_name}' has been deleted.")
