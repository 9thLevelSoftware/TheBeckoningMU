"""
Every Character carries the approval gate in its locks, however it was made.

Only the owning account (traits.CharacterBio.account) may puppet a character,
and only once its CharacterBio is approved; Admins may puppet any character.
The owner may delete it; only Admins edit it.
"""

import evennia
from evennia.locks import lockhandler
from evennia.server.serversession import ServerSession
from evennia.utils import create
from evennia.utils.test_resources import EvenniaTest

from traits.models import CharacterBio
from typeclasses.characters import CHARACTER_LOCKS, Character

CHARACTER = "typeclasses.characters.Character"


def ensure_game_lockfuncs():
    """The lockfunc cache is module-global; a BaseEvenniaTest may have filled it
    with Evennia's template lockfuncs first. Make sure ours are loaded."""
    if "char_owner" not in lockhandler.get_all_lockfuncs():
        lockhandler._cache_lockfuncs()


def login(account, sessid):
    """Log `account` in on a fresh test session and return the session.

    Call logout_all() before the test's tearDown restores the session handler.
    """
    dummy = ServerSession()
    dummy.init_session("telnet", ("localhost", "testmode"), evennia.SESSION_HANDLER)
    dummy.sessid = sessid
    evennia.SESSION_HANDLER.portal_connect(dummy.get_sync_data())
    session = evennia.SESSION_HANDLER.session_from_sessid(sessid)
    evennia.SESSION_HANDLER.login(session, account, testmode=True)
    _LOGGED_IN.append(sessid)
    return session


_LOGGED_IN = []


def logout_all():
    """Drop the sessions login() made, so accounts can be deleted cleanly."""
    while _LOGGED_IN:
        evennia.SESSION_HANDLER.pop(_LOGGED_IN.pop(), None)


class CharacterLockTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        ensure_game_lockfuncs()
        self.player = create.create_account("LockPlayer", email="p@example.com", password="testpassword123")
        self.other = create.create_account("LockOther", email="o@example.com", password="testpassword123")
        self.builder = create.create_account(
            "LockBuilder", email="b@example.com", password="testpassword123", permissions=["Builder"]
        )
        self.admin = create.create_account(
            "LockAdmin", email="a@example.com", password="testpassword123", permissions=["Admin"]
        )

    def tearDown(self):
        logout_all()
        for account in (self.player, self.other, self.builder, self.admin):
            account.delete()
        super().tearDown()

    def make_bio(self, char, account, status="submitted"):
        return CharacterBio.objects.create(character=char, account=account, status=status)

    def test_lockstring_has_the_gate(self):
        char = create.create_object(CHARACTER, key="Gated")
        self.assertEqual(Character.get_default_lockstring(account=self.player), CHARACTER_LOCKS)
        self.assertIn("char_owner() and char_approved()", str(char.locks))
        self.assertNotIn("pid(", str(char.locks))

    def test_raw_create_object_cannot_be_puppeted_by_its_account(self):
        char = create.create_object(CHARACTER, key="RawChar")
        self.player.characters.add(char)
        self.assertFalse(char.access(self.player, "puppet"))

        session = login(self.player, 7)
        self.player.puppet_object(session, char)
        self.assertIsNone(session.puppet)
        self.assertIsNone(char.account)

    def test_character_create_is_gated_until_approved(self):
        char, errors = Character.create("FreshChar", account=self.player)
        self.assertEqual(errors, [])
        self.assertFalse(char.access(self.player, "puppet"))

        bio = self.make_bio(char, self.player)
        self.assertFalse(char.access(self.player, "puppet"))
        for status in ("rejected", "revoked"):
            bio.status = status
            bio.save()
            self.assertFalse(char.access(self.player, "puppet"), status)

        bio.status = "approved"
        bio.save()
        self.assertTrue(char.access(self.player, "puppet"))

        session = login(self.player, 8)
        self.player.puppet_object(session, char)
        self.assertEqual(session.puppet, char)

    def test_only_the_owner_passes_char_owner(self):
        char, _ = Character.create("OwnedChar", account=self.player)
        self.make_bio(char, self.player, status="approved")
        # Being the character's current puppeteer is not ownership.
        char.db_account = self.other
        char.save()
        self.assertFalse(char.access(self.other, "puppet"))
        self.assertTrue(char.access(self.player, "puppet"))

    def test_staff_access(self):
        char, _ = Character.create("PendingChar", account=self.player)
        self.make_bio(char, self.player)
        self.assertFalse(char.access(self.builder, "puppet"))
        self.assertTrue(char.access(self.admin, "puppet"))

    def test_owner_may_delete_others_may_not(self):
        char, _ = Character.create("DeletableChar", account=self.player)
        self.make_bio(char, self.player)
        self.assertTrue(char.access(self.player, "delete"))
        self.assertFalse(char.access(self.other, "delete"))
        self.assertFalse(char.access(self.builder, "delete"))
        self.assertTrue(char.access(self.admin, "delete"))

    def test_only_admins_edit(self):
        char, _ = Character.create("EditChar", account=self.player)
        self.make_bio(char, self.player, status="approved")
        self.assertFalse(char.access(self.player, "edit"))
        self.assertFalse(char.access(self.builder, "edit"))
        self.assertTrue(char.access(self.admin, "edit"))

    def test_a_puppeted_object_is_checked_as_its_account(self):
        char, _ = Character.create("TargetChar", account=self.player)
        self.make_bio(char, self.player, status="approved")
        proxy = create.create_object(CHARACTER, key="ProxyChar")
        proxy.account = self.player
        self.assertTrue(char.access(proxy, "puppet"))
        proxy.account = self.other
        self.assertFalse(char.access(proxy, "puppet"))
