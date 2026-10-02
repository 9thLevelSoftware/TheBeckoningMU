"""
BBS utility functions for permissions and formatting.
"""

from evennia.objects.objects import DefaultObject

from .models import Board, Post


def account_of(caller):
    """The Account behind a caller: a puppeted Object's account, or the Account itself."""
    if isinstance(caller, DefaultObject):
        return caller.account
    return caller


def perm_allows(account, perm):
    """An empty perm (or "all") is open to everyone; otherwise the Account must hold it."""
    if not perm or perm.strip().lower() == "all":
        return True
    return bool(account) and account.check_permstring(perm)


def can_read(account, board, post=None):
    """
    The one read check for boards and posts.

    The board's read perm applies to everything on it; a post's own read
    perm, if set, applies on top. An empty perm means open.
    """
    if not perm_allows(account, board.read_perm):
        return False
    return post is None or perm_allows(account, post.read_perm)


def has_required_flags(caller, board):
    """True if the board needs no flags, or the caller's character has them all."""
    required_flags = board.get_required_flags_list()
    if not required_flags:
        return True
    if not isinstance(caller, DefaultObject):
        return False  # flags live on characters
    char_flags = caller.db.flags or {}
    return all(char_flags.get(flag) for flag in required_flags)


def can_access_board(caller, board):
    """Read perm and required flags together: what lists, counts and reads all use."""
    return can_read(account_of(caller), board) and has_required_flags(caller, board)


def readable_posts(account, board):
    """The board's posts the account may read, oldest first, with authors loaded."""
    if not can_read(account, board):
        return []
    posts = board.posts.select_related("author").order_by("sequence_number")
    return [post for post in posts if can_read(account, board, post)]


def get_board(caller, board_id, check_perm=True):
    """
    Get a board by name or ID.
    
    Args:
        caller: Character or Account object
        board_id: Board name (str) or ID (int)
        check_perm: If True, check read permissions
    
    Returns:
        Board object or None
    """
    try:
        # Try to get by name first, then by ID
        if isinstance(board_id, str):
            board = Board.objects.get(name__iexact=board_id)
        else:
            board = Board.objects.get(id=board_id)
    except Board.DoesNotExist:
        return None
    
    if not check_perm:
        return board
    
    # Read perm and required character flags
    if not can_access_board(caller, board):
        return None

    return board


def get_post(caller, board, post_id, check_perm=True):
    """
    Get a post by sequence number.
    
    Args:
        caller: Character or Account object
        board: Board object
        post_id: Post sequence number (int) or str that can be converted to int
        check_perm: If True, check read permissions
    
    Returns:
        Post object or None
    """
    try:
        post_num = int(post_id)
        post = Post.objects.get(board=board, sequence_number=post_num)
    except (ValueError, Post.DoesNotExist):
        return None
    
    if not check_perm:
        return post
    
    # Check read permissions
    if not can_read(account_of(caller), board, post):
        return None
    
    return post


def format_board_list(caller, boards):
    """
    Formats a list of Board objects into a table view with elegant styling.

    Args:
        caller: The calling character
        boards: List of Board objects

    Returns:
        Formatted string for display
    """
    account = account_of(caller)
    boards = [board for board in boards if can_access_board(caller, board)]
    if not boards:
        return "No boards available."

    # Build elegant table with box borders
    # Border: * + 78 '=' + * = 80 chars total
    # Content: | + space + 76 content + space + | = 80 chars
    # Column widths: 28 + 11 + 24 + 10 = 73, + 3 spaces = 76 content
    table = "|c*" + "=" * 78 + "*|n\n"

    # Format header (all white text, cyan pipes)
    header_content = "|w{:<28} {:<11} {:<24} {:<10}|n".format(
        "Board Name", "Group", "Last Post", "#"
    )
    table += f"|c|||n {header_content} |c|||n\n"
    table += "|c*" + "=" * 78 + "*|n\n"

    # Add each board with proper formatting
    first_board = True
    for board in boards:
        # Add divider between boards (but not before first board)
        if not first_board:
            table += "|c|||n" + "-" * 78 + "|c|||n\n"
        first_board = False

        # Count posts that the caller can read
        posts = readable_posts(account, board)
        post_count = len(posts)

        # Last post among the readable ones only
        last_post = max(posts, key=lambda p: p.created_at) if posts else None
        if last_post:
            author = last_post.get_author_name(account)
            last_post_info = f"{author[:15]} - {last_post.created_at.strftime('%m/%d/%y')}"
        else:
            last_post_info = "No posts"

        # Determine group/category display
        group_display = "IC" if getattr(board, 'is_ic', True) else "OOC"

        # Format row (all white text, cyan pipes)
        row_content = "|w{:<28} {:<11} {:<24} {:<10}|n".format(
            board.name[:28],
            group_display,
            last_post_info[:24],
            str(post_count)
        )
        table += f"|c|||n {row_content} |c|||n\n"

    table += "|c*" + "=" * 78 + "*|n\n"
    return table


def format_board_view(caller, board):
    """
    Formats the list of posts for a given board.

    Args:
        caller: The calling character
        board: Board object

    Returns:
        Formatted string for display
    """
    # Get posts the caller can read
    account = account_of(caller)
    posts = readable_posts(account, board)

    if not posts:
        return f"Board '{board.name}' has no posts or you don't have permission to read them."

    # Build header with box borders (76 char content width)
    output = "|c*" + "=" * 78 + "*|n\n"
    board_header = f"|wBoard: {board.name:<68}|n"
    output += f"|c|||n {board_header} |c|||n\n"
    output += "|c*" + "=" * 78 + "*|n\n"

    # Column header: 5 + 35 + 20 + 13 = 73, + 3 spaces = 76
    col_header = "|w{:<5} {:<35} {:<20} {:<13}|n".format("#", "Title", "Author", "Date")
    output += f"|c|||n {col_header} |c|||n\n"
    output += "|c*" + "=" * 78 + "*|n\n"

    # Add each post
    first_post = True
    for post in posts:
        # Add divider between posts (but not before first post)
        if not first_post:
            output += "|c|||n" + "-" * 78 + "|c|||n\n"
        first_post = False

        author_name = post.get_author_name(account)
        date_str = post.created_at.strftime("%m/%d/%y")

        row_content = "|w{:<5} {:<35} {:<20} {:<13}|n".format(
            post.sequence_number,
            post.title[:35],
            author_name[:20],
            date_str
        )
        output += f"|c|||n {row_content} |c|||n\n"

    output += "|c*" + "=" * 78 + "*|n\n"
    return output


def format_post_read(post, viewer=None):
    """
    Formats a single post and its comments for reading.

    Args:
        post: Post object
        viewer: The viewer's Account (decides whether an anonymous author shows)

    Returns:
        Formatted string for display
    """
    author_name = post.get_author_name(account_of(viewer))
    date_str = post.created_at.strftime("%B %d, %Y at %I:%M %p")

    # Post header with box borders (76 char content width)
    output = "|c*" + "=" * 78 + "*|n\n"
    post_title = f"|wPost #{post.sequence_number}: {post.title:<60}|n"
    output += f"|c|||n {post_title} |c|||n\n"
    post_author = f"|wBy: {author_name} on {date_str:<56}|n"
    output += f"|c|||n {post_author} |c|||n\n"
    output += "|c*" + "=" * 78 + "*|n\n"

    # Post body - wrap lines and add borders (76 char content width)
    body_lines = post.body.split('\n')
    for line in body_lines:
        # Handle long lines by wrapping at 76 characters
        while len(line) > 76:
            output += f"|c|||n |w{line[:76]:<76}|n |c|||n\n"
            line = line[76:]
        output += f"|c|||n |w{line:<76}|n |c|||n\n"

    # Comments
    comments = post.comments.all()
    if comments:
        output += "|c*" + "=" * 78 + "*|n\n"
        comment_header = f"|wComments:{' ' * 64}|n"
        output += f"|c|||n {comment_header} |c|||n\n"
        output += "|c*" + "=" * 78 + "*|n\n"

        first_comment = True
        for comment in comments:
            # Add divider between comments (but not before first comment)
            if not first_comment:
                output += "|c|||n" + "-" * 78 + "|c|||n\n"
            first_comment = False

            if post.is_anonymous and comment.author_id == post.author_id:
                # The anonymous poster replying in their own thread stays anonymous.
                comment_author = post.get_author_name(account_of(viewer))
            else:
                comment_author = comment.author.username if comment.author else "Unknown"
            comment_date = comment.created_at.strftime("%m/%d/%y %I:%M %p")

            comment_header = f"|w{comment_author}|n ({comment_date}):{' ' * (52 - len(comment_author) - len(comment_date))}"
            output += f"|c|||n {comment_header} |c|||n\n"

            # Wrap comment body
            comment_lines = comment.body.split('\n')
            for line in comment_lines:
                while len(line) > 76:
                    output += f"|c|||n |w{line[:76]:<76}|n |c|||n\n"
                    line = line[76:]
                output += f"|c|||n |w{line:<76}|n |c|||n\n"

    output += "|c*" + "=" * 78 + "*|n\n"
    return output
