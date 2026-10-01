"""
Jobs utility functions for shared functionality across job commands.
"""

from django.db.models import Q
from evennia.accounts.models import AccountDB
from evennia.objects.objects import DefaultObject

from .models import Bucket, Job

STAFF_PERM = "Builder"


def account_of(caller):
    """The Account behind a caller: a puppeted Object's account, or the Account itself."""
    if isinstance(caller, DefaultObject):
        return caller.account
    return caller


def is_staff(caller):
    """True if the caller's Account holds Builder or higher (superusers included)."""
    account = account_of(caller)
    return bool(account) and account.check_permstring(STAFF_PERM)


def jobs_visible_to(caller, queryset=None):
    """Restrict a Job queryset to what the caller may see (see can_view_job)."""
    queryset = Job.objects.all() if queryset is None else queryset
    queryset = queryset.select_related("bucket").prefetch_related("players")
    if is_staff(caller):
        return queryset
    account = account_of(caller)
    if not account:
        return queryset.none()
    return queryset.filter(
        Q(creator=account) | Q(assigned_to=account) | Q(players=account)
    ).distinct()


def get_job(caller, job_ref, bucket=None):
    """
    Find a Job by `<bucket>/<n>`, or by a bare `<n>` when only one bucket has it.

    Sequence numbers are per bucket, so a bare number that exists in more
    than one bucket is ambiguous and is refused.

    Args:
        caller: The calling character (receives error messages)
        job_ref: "<bucket>/<n>", "<n>" or an int
        bucket: Optional Bucket to search within

    Returns:
        Job object or None, messaging the caller on failure.
    """
    job_ref = str(job_ref).strip()
    if bucket is None and "/" in job_ref:
        bucket_name, job_ref = job_ref.rsplit("/", 1)
        bucket = get_bucket(caller, bucket_name.strip())
        if not bucket:
            return None
    try:
        number = int(job_ref)
    except ValueError:
        caller.msg(f"Job '{job_ref}' not found. Use <bucket>/<number>.")
        return None

    jobs = Job.objects.select_related("bucket").filter(sequence_number=number)
    if bucket is not None:
        jobs = jobs.filter(bucket=bucket)
    jobs = list(jobs[:5])
    if not jobs:
        where = f"{bucket.name}/{number}" if bucket is not None else f"#{number}"
        caller.msg(f"Job {where} not found.")
        return None
    if len(jobs) > 1:
        refs = ", ".join(job.ref for job in jobs)
        caller.msg(f"Job #{number} is ambiguous; use <bucket>/{number} ({refs}).")
        return None
    return jobs[0]


def get_bucket(caller, bucket_name):
    """
    Fetches a Bucket by name with error handling.
    
    Args:
        caller: The calling character
        bucket_name: Bucket name string
    
    Returns:
        Bucket object or None, messaging the caller on failure.
    """
    try:
        bucket = Bucket.objects.get(name__iexact=bucket_name)
        return bucket
    except Bucket.DoesNotExist:
        caller.msg(f"Bucket '{bucket_name}' not found.")
        return None


def get_account(caller, account_name):
    """
    Fetches an AccountDB by username with error handling.
    
    Args:
        caller: The calling character
        account_name: Account username string
    
    Returns:
        AccountDB object or None, messaging the caller on failure.
    """
    try:
        account = AccountDB.objects.get(username__iexact=account_name)
        return account
    except AccountDB.DoesNotExist:
        caller.msg(f"Account '{account_name}' not found.")
        return None


def _is_party(account, job):
    """Creator, primary assignee or one of the job's players."""
    if not account:
        return False
    return (
        job.creator_id == account.id
        or job.assigned_to_id == account.id
        or job.players.filter(id=account.id).exists()
    )


def check_job_permission(caller, job):
    """
    True if the caller may comment on a job: staff, its creator or an assignee.
    """
    return is_staff(caller) or _is_party(account_of(caller), job)


def format_job_view(job, viewer):
    """
    Returns a formatted string for detailed job view.

    Private comments are staff-only: a non-staff viewer sees only public
    comments and private ones they wrote themselves.

    Args:
        job: Job object
        viewer: The character or account looking at the job

    Returns:
        Formatted string for display
    """
    # Header with box border
    output = "\n|c*" + "=" * 78 + "*|n\n"

    # Title
    title_text = f"|wJob {job.ref}: {job.title}|n"
    title_len = len(f"Job {job.ref}: {job.title}")  # Calculate without color codes
    padding = 74 - title_len
    output += f"|c|||n {title_text}{' ' * padding} |c|||n\n"
    output += "|c*" + "=" * 78 + "*|n\n\n"

    # Job details
    status_color = "|g" if job.status == "OPEN" else "|r" if job.completed else "|y"
    output += f"|wBucket:|n {job.bucket.name}\n"
    output += f"|wStatus:|n {status_color}{job.status}|n\n"
    output += f"|wCreated by:|n {job.creator.username}\n"
    output += f"|wCreated:|n {job.created_at.strftime('%B %d, %Y at %I:%M %p')}\n"

    # Assigned players
    players = job.players.all()
    if players:
        player_names = [p.username for p in players]
        output += f"|wAssigned to:|n {', '.join(player_names)}\n"
    else:
        output += f"|wAssigned to:|n None\n"

    # Completion status
    if job.completed:
        output += f"|wCompleted:|n Yes\n"
    else:
        output += f"|wCompleted:|n No\n"

    output += "\n|wDescription:|n\n"
    output += f"{job.description}\n"

    # Comments
    comments = job.comments.select_related("author")
    if not is_staff(viewer):
        account = account_of(viewer)
        comments = comments.filter(Q(public=True) | Q(author=account))
    if comments:
        output += "\n|wComments:|n\n"
        output += "-" * 60 + "\n"

        for comment in comments:
            author_name = comment.author.username if comment.author else "System"
            date_str = comment.created_at.strftime("%m/%d/%y %I:%M %p")
            visibility = " (Public)" if comment.public else " (Private)"

            output += f"|w{author_name}|n{visibility} ({date_str}):\n"
            output += f"{comment.content}\n\n"

    return output


def format_job_list(jobs, title="Jobs"):
    """
    Returns a formatted string for a list of jobs.

    Args:
        jobs: QuerySet or list of Job objects
        title: Title for the list

    Returns:
        Formatted string for display
    """
    if not jobs:
        # Handle specific messaging for different contexts
        if title == "All Open Jobs":
            return "There are no jobs."
        elif title == "My Jobs":
            return "You have no jobs submitted."
        else:
            return f"No {title.lower()} found."

    # Box border header, then the list's title
    output = "\n|c*" + "=" * 78 + "*|n\n"
    output += f"|c|||n |w{title[:76]:<76}|n |c|||n\n"
    output += "|c*" + "=" * 78 + "*|n\n"

    # Header row (ID=4, Title=28, Bucket=15, Status=8, Assigned=15 = 70 + 4 spaces = 74)
    header_content = "|w{:<4} {:<28} {:<15} {:<8} {:<15}|n".format(
        "ID", "Title", "Bucket", "Status", "Assigned"
    )
    output += f"|c|||n {header_content} |c|||n\n"
    output += "|c*" + "=" * 78 + "*|n\n"

    # Jobs with dividers
    first_job = True
    for job in jobs:
        if not first_job:
            output += "|c|||n" + "-" * 78 + "|c|||n\n"
        first_job = False

        # Get assigned players (prefetched by the callers)
        players = list(job.players.all())
        if players:
            assigned = players[0].username[:14]
            if len(players) > 1:
                assigned += " (+)"
        else:
            assigned = "None"

        # Status formatting
        status = job.status
        if job.completed:
            status = "CLOSED"

        row_content = "|w{:<4} {:<28} {:<15} {:<8} {:<15}|n".format(
            str(job.sequence_number),
            job.title[:28],
            job.bucket.name[:15],
            status[:8],
            assigned
        )
        output += f"|c|||n {row_content} |c|||n\n"

    output += "|c*" + "=" * 78 + "*|n\n"
    return output


def format_bucket_list(buckets):
    """
    Returns a formatted string for a list of buckets.

    Args:
        buckets: QuerySet or list of Bucket objects

    Returns:
        Formatted string for display
    """
    if not buckets:
        return "No buckets found."

    # Box border header
    output = "\n|c*" + "=" * 78 + "*|n\n"

    # Header row (Name=20, Jobs=8, Description=44 = 72 + 2 spaces = 74)
    header_content = "|w{:<20} {:<8} {:<44}|n".format("Name", "Jobs", "Description")
    output += f"|c|||n {header_content} |c|||n\n"
    output += "|c*" + "=" * 78 + "*|n\n"

    # Buckets with dividers
    first_bucket = True
    for bucket in buckets:
        if not first_bucket:
            output += "|c|||n" + "-" * 78 + "|c|||n\n"
        first_bucket = False

        job_count = bucket.jobs.count()
        description = bucket.description[:44] if bucket.description else "No description"

        row_content = "|w{:<20} {:<8} {:<44}|n".format(
            bucket.name[:20],
            str(job_count),
            description
        )
        output += f"|c|||n {row_content} |c|||n\n"

    output += "|c*" + "=" * 78 + "*|n\n"
    return output


def can_view_job(caller, job):
    """
    True if the caller may see a job: staff, its creator or an assignee.
    """
    return is_staff(caller) or _is_party(account_of(caller), job)


def can_modify_job(caller, job):
    """
    True if the caller may modify a job (same rule as commenting).
    """
    return check_job_permission(caller, job)


def can_complete_job(caller, job):
    """
    True if the caller may close a job: staff, or the creator withdrawing it.

    Assignees who aren't staff can't close a job, so a player added to a job
    can't close someone else's request.
    """
    if is_staff(caller):
        return True
    account = account_of(caller)
    return bool(account) and job.creator_id == account.id
