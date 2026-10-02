"""
Removed creation and export paths stay removed.

Characters are created only through the website form, and builder areas reach
the live world only through review and promotion. These tests fail if any of
the retired shortcuts comes back.
"""

from django.test import Client, TestCase
from evennia.utils.test_resources import EvenniaTest

from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet

REMOVED_COMMANDS = ("charcreate", "+chargen", "+setstat", "+setdisc", "@promote", "@abandon", "@cleanup_sandbox")


class TestRemovedCommands(TestCase):
    def test_removed_commands_not_in_cmdsets(self):
        keys = set()
        for cmdset_class in (AccountCmdSet, CharacterCmdSet):
            cmdset = cmdset_class()
            cmdset.at_cmdset_creation()
            keys.update(cmdset.get_all_cmd_keys_and_aliases())

        for key in REMOVED_COMMANDS:
            self.assertNotIn(key, keys, msg=f"{key} should not be registered")

        # The cmdset still carries the commands this PR keeps.
        self.assertIn("chardelete", keys)
        self.assertIn("ic", keys)
        self.assertIn("roll", keys)


class TestOOCMenu(EvenniaTest):
    def test_ooc_menu_points_to_website(self):
        # target=[] renders the menu as for an account with no characters, which
        # exercises the rewrite of Evennia's "Use charcreate" line as well as
        # the menu template.
        text = self.account.at_look(target=[], session=self.session)
        self.assertIn("/character-creation/", text)
        self.assertNotIn("charcreate", text)
        self.assertIn("You don't have a character yet", text)


class TestRemovedRoutes(TestCase):
    def setUp(self):
        self.client = Client()

    def test_builder_export_route_removed(self):
        self.assertEqual(self.client.get("/builder/export/1/").status_code, 404)

    def test_character_import_route_removed(self):
        self.assertEqual(self.client.post("/api/traits/character/import/").status_code, 404)

    def test_builder_cleanup_route_removed(self):
        self.assertEqual(self.client.post("/builder/api/build/1/cleanup/").status_code, 404)
