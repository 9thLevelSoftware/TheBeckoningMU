"""
BBS read permissions and author display (F-028, F-029).

Players are real puppeted characters whose accounts hold no permissions;
staff is an Admin account.
"""

from django.conf import settings
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import CmdBBS, CmdBBSRead
from .models import Board, Post
from .utils import can_read, format_board_list, format_board_view, format_post_read


class BBSReadTests(EvenniaCommandTest):
    def _puppet(self, name, *perms):
        account = create.create_account(name, email=f"{name}@example.com", password="pw123456")
        for perm in perms:
            account.permissions.add(perm)
        char = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key=name, location=self.room1, home=self.room1)
        char.account = account
        return account, char

    def setUp(self):
        super().setUp()
        self.mallory_account, self.mallory = self._puppet("Mallory")
        self.bob_account, self.bob = self._puppet("Bob")
        self.staff_account, self.staff = self._puppet("Warden", "Admin")
        self.board = Board.objects.create(name="General", description="General chat")
        self.post = Post.objects.create(
            board=self.board, author=self.mallory_account, title="Hello world", body="First!"
        )

    def test_empty_read_perm_is_open_to_players(self):
        """A non-superuser sees posts on a board and post with no read perm."""
        self.assertEqual(self.board.read_perm, "")
        self.assertEqual(self.post.read_perm, "")
        self.assertTrue(can_read(self.bob_account, self.board, self.post))

        output = self.call(CmdBBS(), "General", caller=self.bob)
        self.assertIn("Hello world", output)

        output = self.call(CmdBBSRead(), "General/1", caller=self.bob)
        self.assertIn("First!", output)

    def test_restricted_post_hidden_from_players(self):
        secret = Post.objects.create(
            board=self.board,
            author=self.staff_account,
            title="Staff secret",
            body="classified",
            read_perm="Admin",
        )
        self.assertFalse(can_read(self.bob_account, self.board, secret))
        self.assertNotIn("Staff secret", format_board_view(self.bob, self.board))
        # The board list counts and dates only what Bob can read.
        board_list = format_board_list(self.bob, [self.board])
        self.assertNotIn("Warden", board_list)
        self.assertIn("Mallory", board_list)

        self.assertIn("Staff secret", format_board_view(self.staff, self.board))
        output = self.call(CmdBBSRead(), "General/2", caller=self.bob)
        self.assertIn("not found", output)

    def test_restricted_board_hidden_from_players(self):
        self.board.read_perm = "Admin"
        self.board.save()
        self.assertFalse(can_read(self.bob_account, self.board))
        self.assertEqual(format_board_list(self.bob, [self.board]), "No boards available.")
        self.assertIn("General", format_board_list(self.staff, [self.board]))

    def test_anonymous_post_hides_author_from_players(self):
        Post.objects.create(
            board=self.board,
            author=self.mallory_account,
            title="Whisper",
            body="A secret",
            is_anonymous=True,
        )
        Post.objects.filter(board=self.board, sequence_number=1).delete()
        anon = Post.objects.get(board=self.board, title="Whisper")

        read = format_post_read(anon, viewer=self.bob_account)
        self.assertNotIn("Mallory", read)
        self.assertIn("Anonymous", read)
        self.assertNotIn("Mallory", format_board_view(self.bob, self.board))
        self.assertNotIn("Mallory", format_board_list(self.bob, [self.board]))
        self.assertNotIn("Mallory", self.call(CmdBBSRead(), "General/2", caller=self.bob))

        # The author and staff still see who wrote it.
        self.assertIn("Mallory", format_post_read(anon, viewer=self.mallory_account))
        self.assertIn("Mallory", format_post_read(anon, viewer=self.staff_account))
