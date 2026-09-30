"""
BBS commands for bulletin board system.
"""

from evennia.commands.command import Command
from evennia import default_cmds
from evennia.commands.cmdset import CmdSet
from django.db import IntegrityError, OperationalError
from django.core.exceptions import ValidationError
from .models import Board, Post, Comment
from .utils import get_board, get_post, format_board_list, format_board_view, format_post_read


class CmdBBS(Command):
    """
    List boards or view a specific board.
    
    Usage:
        +bbs
        +bbs <board>
    
    Examples:
        +bbs                - List all available boards
        +bbs general        - View posts on the 'general' board
    
    Lists all available bulletin boards or views posts on a specific board.
    Boards are filtered by your character's flags and permissions.
    """
    
    key = "+bbs"
    aliases = ["bbs"]
    locks = "cmd:all()"
    help_category = "Communication"
    
    def func(self):
        """Execute command."""
        if not self.args.strip():
            # List all boards
            boards = Board.objects.all()
            output = format_board_list(self.caller, boards)
            self.caller.msg(output)
        else:
            # View specific board
            board_name = self.args.strip()
            board = get_board(self.caller, board_name)
            
            if not board:
                self.caller.msg(f"Board '{board_name}' not found or you don't have permission to view it.")
                return
            
            output = format_board_view(self.caller, board)
            self.caller.msg(output)


class CmdBBSRead(Command):
    """
    Read a specific post with comments.
    
    Usage:
        +bbread <board>/<post#>
    
    Examples:
        +bbread general/1   - Read post #1 on the 'general' board
        +bbread admin/5     - Read post #5 on the 'admin' board
    
    Displays the full content of a post including all comments.
    """
    
    key = "+bbread"
    aliases = ["bbread"]
    locks = "cmd:all()"
    help_category = "Communication"
    
    def func(self):
        """Execute command."""
        if not self.args or '/' not in self.args:
            self.caller.msg("Usage: +bbread <board>/<post#>")
            return
        
        try:
            board_name, post_num = self.args.split('/', 1)
            board_name = board_name.strip()
            post_num = post_num.strip()
        except ValueError:
            self.caller.msg("Usage: +bbread <board>/<post#>")
            return
        
        # Get board
        board = get_board(self.caller, board_name)
        if not board:
            self.caller.msg(f"Board '{board_name}' not found or you don't have permission to view it.")
            return
        
        # Get post
        post = get_post(self.caller, board, post_num)
        if not post:
            self.caller.msg(f"Post #{post_num} not found on board '{board_name}'.")
            return
        
        # Get viewer account
        account = self.caller.account if hasattr(self.caller, 'account') else self.caller
        
        # Display post
        output = format_post_read(post, viewer=account)
        self.caller.msg(output)


class CmdBBSPost(default_cmds.MuxCommand):
    """
    Create a new post on a board.

    Usage:
        +bbpost <board>=<title>/<body>
        +bbpost/anon <board>=<title>/<body>

    Examples:
        +bbpost general=Hello/This is my first post!
        +bbpost admin=Meeting Notes/We discussed...
        +bbpost/anon rumors=Heard something/I heard a rumor...

    Creates a new post on the specified board. The title and body
    are separated by a forward slash (/).

    The /anon switch creates an anonymous post. Anonymous posts show
    as "Anonymous" to regular users, but staff can still see the true
    author. Not all boards allow anonymous posting.
    """

    key = "+bbpost"
    aliases = ["bbpost"]
    locks = "cmd:all()"
    help_category = "Communication"
    
    def func(self):
        """Execute command."""
        if not self.args or '=' not in self.args:
            self.caller.msg("Usage: +bbpost <board>=<title>/<body>")
            return

        # Check for /anon switch
        is_anonymous = "anon" in self.switches

        # Parse arguments
        board_name = self.lhs.strip() if self.lhs else ""

        if not self.rhs or '/' not in self.rhs:
            self.caller.msg("Usage: +bbpost <board>=<title>/<body>")
            return

        try:
            title, body = self.rhs.split('/', 1)
            title = title.strip()
            body = body.strip()
        except ValueError:
            self.caller.msg("Usage: +bbpost <board>=<title>/<body>")
            return

        if not board_name or not title or not body:
            self.caller.msg("Board name, title, and body are all required.")
            return

        # Get board
        board = get_board(self.caller, board_name, check_perm=False)
        if not board:
            self.caller.msg(f"Board '{board_name}' not found.")
            return

        # Check if anonymous posting is allowed on this board
        if is_anonymous and not board.allow_anonymous:
            self.caller.msg(f"Board '{board_name}' does not allow anonymous posting.")
            return

        # Check write permissions
        if board.write_perm:
            account = self.caller.account if hasattr(self.caller, 'account') else self.caller
            if not account.check_permstring(board.write_perm):
                self.caller.msg(f"You don't have permission to post to '{board_name}'.")
                return

        # Check required flags
        required_flags = board.get_required_flags_list()
        if required_flags:
            character = self.caller if hasattr(self.caller, 'db') else None
            if character:
                char_flags = character.db.flags or {}
                missing_flags = [flag for flag in required_flags if not char_flags.get(flag)]
                if missing_flags:
                    self.caller.msg(f"You don't have the required flags to post to '{board_name}'.")
                    return
            else:
                self.caller.msg(f"You don't have the required flags to post to '{board_name}'.")
                return

        # Get account
        account = self.caller.account if hasattr(self.caller, 'account') else self.caller

        # Create post
        try:
            post = Post.objects.create(
                author=account,
                board=board,
                title=title,
                body=body,
                is_anonymous=is_anonymous
            )

            if is_anonymous:
                self.caller.msg(f"Posted anonymously to '{board.name}' as post #{post.sequence_number}.")
            else:
                self.caller.msg(f"Posted to '{board.name}' as post #{post.sequence_number}.")
        except (IntegrityError, ValidationError) as e:
            self.caller.msg(f"Error creating post: {e}")
        except OperationalError as e:
            self.caller.msg(f"Database error creating post: {e}")


class CmdBBSComment(default_cmds.MuxCommand):
    """
    Add a comment to a post.

    Usage:
        +bbcomment <board>/<post#>=<comment>
    
    Examples:
        +bbcomment general/1=Great post!
        +bbcomment admin/5=I agree with this.
    
    Adds a comment to an existing post on a board.
    """
    
    key = "+bbcomment"
    aliases = ["bbcomment"]
    locks = "cmd:all()"
    help_category = "Communication"
    
    def func(self):
        """Execute command."""
        if not self.args or '=' not in self.args:
            self.caller.msg("Usage: +bbcomment <board>/<post#>=<comment>")
            return
        
        # Parse arguments
        if not self.lhs or '/' not in self.lhs:
            self.caller.msg("Usage: +bbcomment <board>/<post#>=<comment>")
            return
        
        try:
            board_name, post_num = self.lhs.split('/', 1)
            board_name = board_name.strip()
            post_num = post_num.strip()
        except ValueError:
            self.caller.msg("Usage: +bbcomment <board>/<post#>=<comment>")
            return
        
        comment_body = self.rhs.strip() if self.rhs else ""
        
        if not board_name or not post_num or not comment_body:
            self.caller.msg("Board name, post number, and comment text are all required.")
            return
        
        # Get board
        board = get_board(self.caller, board_name)
        if not board:
            self.caller.msg(f"Board '{board_name}' not found or you don't have permission to view it.")
            return
        
        # Get post
        post = get_post(self.caller, board, post_num)
        if not post:
            self.caller.msg(f"Post #{post_num} not found on board '{board_name}'.")
            return
        
        # Check write permissions
        perm_to_check = post.write_perm or board.write_perm
        if perm_to_check:
            account = self.caller.account if hasattr(self.caller, 'account') else self.caller
            if not account.check_permstring(perm_to_check):
                self.caller.msg(f"You don't have permission to comment on this post.")
                return
        
        # Get account
        account = self.caller.account if hasattr(self.caller, 'account') else self.caller
        
        # Create comment
        try:
            comment = Comment.objects.create(
                author=account,
                post=post,
                body=comment_body
            )
            self.caller.msg(f"Added comment to post #{post.sequence_number} on '{board.name}'.")
        except (IntegrityError, ValidationError) as e:
            self.caller.msg(f"Error creating comment: {e}")
        except OperationalError as e:
            self.caller.msg(f"Database error creating comment: {e}")


class CmdBBSDelete(default_cmds.MuxCommand):
    """
    Delete a post (admin only).

    Usage:
        +bbdelete/post <board>/<post#>
    
    Examples:
        +bbdelete/post general/1    - Delete post #1 on general board
    
    Permanently deletes a post and all its comments. Admin only.
    """
    
    key = "+bbdelete"
    aliases = ["bbdelete"]
    locks = "cmd:pperm(Admin)"
    help_category = "Communication"
    
    def func(self):
        """Execute command."""
        if "post" not in self.switches:
            self.caller.msg("Usage: +bbdelete/post <board>/<post#>")
            return
        
        if not self.args or '/' not in self.args:
            self.caller.msg("Usage: +bbdelete/post <board>/<post#>")
            return
        
        try:
            board_name, post_num = self.args.split('/', 1)
            board_name = board_name.strip()
            post_num = post_num.strip()
        except ValueError:
            self.caller.msg("Usage: +bbdelete/post <board>/<post#>")
            return
        
        # Get board
        board = get_board(self.caller, board_name, check_perm=False)
        if not board:
            self.caller.msg(f"Board '{board_name}' not found.")
            return
        
        # Get post
        post = get_post(self.caller, board, post_num, check_perm=False)
        if not post:
            self.caller.msg(f"Post #{post_num} not found on board '{board_name}'.")
            return
        
        # Delete post
        try:
            post.delete()
            self.caller.msg(f"Deleted post #{post_num} from '{board.name}'.")
        except (IntegrityError, ValidationError) as e:
            self.caller.msg(f"Error deleting post: {e}")
        except OperationalError as e:
            self.caller.msg(f"Database error deleting post: {e}")


class CmdBBSAdmin(default_cmds.MuxCommand):
    """
    Administer bulletin boards (admin only).

    Usage:
        +bbadmin/create <name>=<description>
        +bbadmin/edit <board>/<field>=<value>
        +bbadmin/delete <board>
    
    Examples:
        +bbadmin/create general=General discussion board
        +bbadmin/edit general/description=A board for general chat
        +bbadmin/edit general/read_perm=Player
        +bbadmin/edit general/write_perm=Builder
        +bbadmin/edit general/is_ic=True
        +bbadmin/edit general/allow_anonymous=True
        +bbadmin/edit general/required_flags=vampire,elder
        +bbadmin/delete oldboard
    
    Creates, edits, or deletes bulletin boards. Admin only.
    
    Valid fields for /edit:
        description, read_perm, write_perm, is_ic, 
        allow_anonymous, required_flags
    """
    
    key = "+bbadmin"
    aliases = ["bbadmin"]
    locks = "cmd:pperm(Admin)"
    help_category = "Communication"
    
    def func(self):
        """Execute command."""
        if not self.switches:
            self.caller.msg("Usage: +bbadmin/create, +bbadmin/edit, or +bbadmin/delete")
            return
        
        switch = self.switches[0].lower()
        
        if switch == "create":
            self.do_create()
        elif switch == "edit":
            self.do_edit()
        elif switch == "delete":
            self.do_delete()
        else:
            self.caller.msg(f"Unknown switch: {switch}")
    
    def do_create(self):
        """Create a new board."""
        if not self.args or '=' not in self.args:
            self.caller.msg("Usage: +bbadmin/create <name>=<description>")
            return
        
        name = self.lhs.strip() if self.lhs else ""
        description = self.rhs.strip() if self.rhs else ""
        
        if not name or not description:
            self.caller.msg("Both name and description are required.")
            return
        
        # Check if board already exists
        if Board.objects.filter(name__iexact=name).exists():
            self.caller.msg(f"Board '{name}' already exists.")
            return
        
        # Create board
        try:
            board = Board.objects.create(
                name=name,
                description=description
            )
            self.caller.msg(f"Created board '{board.name}'.")
        except (IntegrityError, ValidationError) as e:
            self.caller.msg(f"Error creating board: {e}")
        except OperationalError as e:
            self.caller.msg(f"Database error creating board: {e}")
    
    def do_edit(self):
        """Edit a board."""
        if not self.args or '=' not in self.args or '/' not in self.lhs:
            self.caller.msg("Usage: +bbadmin/edit <board>/<field>=<value>")
            return
        
        try:
            board_name, field = self.lhs.split('/', 1)
            board_name = board_name.strip()
            field = field.strip()
        except ValueError:
            self.caller.msg("Usage: +bbadmin/edit <board>/<field>=<value>")
            return
        
        value = self.rhs.strip() if self.rhs else ""
        
        # Get board
        board = get_board(self.caller, board_name, check_perm=False)
        if not board:
            self.caller.msg(f"Board '{board_name}' not found.")
            return
        
        # Valid fields
        valid_fields = [
            'description', 'read_perm', 'write_perm', 
            'is_ic', 'allow_anonymous', 'required_flags'
        ]
        
        if field not in valid_fields:
            self.caller.msg(f"Invalid field: {field}. Valid fields: {', '.join(valid_fields)}")
            return
        
        # Set field
        try:
            if field in ['is_ic', 'allow_anonymous']:
                # Boolean fields
                value_lower = value.lower()
                if value_lower in ['true', '1', 'yes', 'on']:
                    setattr(board, field, True)
                elif value_lower in ['false', '0', 'no', 'off']:
                    setattr(board, field, False)
                else:
                    self.caller.msg(f"Invalid boolean value: {value}")
                    return
            else:
                # String fields
                setattr(board, field, value)
            
            board.save()
            self.caller.msg(f"Updated {field} for board '{board.name}'.")
        except (IntegrityError, ValidationError) as e:
            self.caller.msg(f"Error updating board: {e}")
        except OperationalError as e:
            self.caller.msg(f"Database error updating board: {e}")
    
    def do_delete(self):
        """Delete a board."""
        if not self.args:
            self.caller.msg("Usage: +bbadmin/delete <board>")
            return
        
        board_name = self.args.strip()
        
        # Get board
        board = get_board(self.caller, board_name, check_perm=False)
        if not board:
            self.caller.msg(f"Board '{board_name}' not found.")
            return
        
        # Delete board
        try:
            board_name = board.name
            board.delete()
            self.caller.msg(f"Deleted board '{board_name}'.")
        except (IntegrityError, ValidationError) as e:
            self.caller.msg(f"Error deleting board: {e}")
        except OperationalError as e:
            self.caller.msg(f"Database error deleting board: {e}")


class BBSCmdSet(CmdSet):
    """
    Command set containing all BBS commands.
    """
    
    key = "BBSCmdSet"
    
    def at_cmdset_creation(self):
        """Add all BBS commands."""
        self.add(CmdBBS())
        self.add(CmdBBSRead())
        self.add(CmdBBSPost())
        self.add(CmdBBSComment())
        self.add(CmdBBSDelete())
        self.add(CmdBBSAdmin())
