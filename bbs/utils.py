"""
BBS utility functions for permissions and formatting.
"""

from evennia.utils.utils import crop
from .models import Board, Post


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
    
    # Check read permissions
    if board.read_perm:
        account = caller.account if hasattr(caller, 'account') else caller
        if not account.check_permstring(board.read_perm):
            return None
    
    # Check required flags
    required_flags = board.get_required_flags_list()
    if required_flags:
        # Get character flags
        character = caller if hasattr(caller, 'db') else None
        if character:
            char_flags = character.db.flags or {}
            # Check if character has all required flags
            for flag in required_flags:
                if not char_flags.get(flag):
                    return None
        else:
            # No character, can't check flags
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
    perm_to_check = post.read_perm or board.read_perm
    if perm_to_check:
        account = caller.account if hasattr(caller, 'account') else caller
        if not account.check_permstring(perm_to_check):
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
        readable_posts = [p for p in board.posts.all()
                         if p.read_perm == 'all' or caller.check_permstring(p.read_perm)]
        post_count = len(readable_posts)

        # Get last post info
        last_post = board.posts.order_by('-created_at').first() if readable_posts else None
        if last_post:
            last_post_info = f"{last_post.author.username[:15]} - {last_post.created_at.strftime('%m/%d/%y')}"
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
    readable_posts = []
    for post in board.posts.all():
        if post.read_perm == 'all' or caller.check_permstring(post.read_perm):
            readable_posts.append(post)

    if not readable_posts:
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
    for post in readable_posts:
        # Add divider between posts (but not before first post)
        if not first_post:
            output += "|c|||n" + "-" * 78 + "|c|||n\n"
        first_post = False

        author_name = post.author.username if post.author else "Unknown"
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
        viewer: AccountDB object of the viewer (optional, for compatibility)

    Returns:
        Formatted string for display
    """
    author_name = post.author.username if post.author else "Unknown"
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
