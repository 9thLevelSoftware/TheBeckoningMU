"""
Staff and player tools added in PR 10 review round 1: default data seeded at
server start, player job buckets, jobs out of character, +torpor, +npc and
the +hunt/staffed job.
"""

from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest

from bbs.models import Board
from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet
from commands.v5.hunt import CmdHunt
from commands.v5.staff import CmdNPC, CmdTorpor
from jobs.commands import CmdBuckets, CmdJobSubmit, CmdJobView
from jobs.models import Bucket, Job
from status.models import CamarillaPosition
from world.seed_defaults import DEFAULT_BOARDS, seed_defaults


def _make_player(test):
    """char2/account2 with nothing above Player."""
    test.char2.permissions.remove("Developer")
    test.account2.permissions.remove("Developer")
    return test.char2


class SeedDefaultsTests(EvenniaCommandTest):
    def test_seeds_once_and_is_idempotent(self):
        first = seed_defaults()
        self.assertEqual(first["job buckets"], 5)
        self.assertGreater(first["positions"], 0)
        self.assertEqual(first["boards"], len(DEFAULT_BOARDS))
        self.assertEqual(seed_defaults(), {"job buckets": 0, "positions": 0, "boards": 0})
        self.assertEqual(
            set(Bucket.objects.filter(player_submit=True).values_list("name", flat=True)), {"Requests", "Bugs"}
        )
        for name in ("Approval", "Hunt Scenes", "Builds"):
            self.assertFalse(Bucket.objects.get(name=name).player_submit)
        self.assertTrue(CamarillaPosition.objects.filter(name="Primogen").exists())
        self.assertEqual(Board.objects.get(name="policy").write_perm, "Builder")

    def test_existing_rows_are_not_changed(self):
        Bucket.objects.create(name="Bugs", description="ours", player_submit=False)
        seed_defaults()
        bugs = Bucket.objects.get(name="Bugs")
        self.assertEqual((bugs.description, bugs.player_submit), ("ours", False))

    def test_server_start_seeds(self):
        from server.conf.at_server_startstop import at_server_start

        at_server_start()
        self.assertTrue(Bucket.objects.filter(name="Requests").exists())
        self.assertTrue(Board.objects.filter(name="general").exists())


class PlayerBucketTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        seed_defaults()
        self.player = _make_player(self)

    def test_players_list_only_player_buckets(self):
        out = self.call(CmdBuckets(), "", caller=self.player)
        self.assertIn("Requests", out)
        self.assertIn("Bugs", out)
        self.assertNotIn("Approval", out)
        self.assertNotIn("Builds", out)
        staff = self.call(CmdBuckets(), "", caller=self.char1)
        self.assertIn("Approval", staff)

    def test_players_submit_only_to_player_buckets(self):
        out = self.call(CmdJobSubmit(), "Builds Fix the door = it sticks", caller=self.player)
        self.assertIn("can't file jobs in 'Builds'", out)
        self.assertFalse(Job.objects.filter(bucket__name="Builds").exists())
        self.call(CmdJobSubmit(), "Requests Scene please = Friday at Elysium", caller=self.player)
        job = Job.objects.get(bucket__name="Requests")
        self.assertEqual(job.creator, self.account2)
        self.call(CmdJobSubmit(), "Builds Staff note = fine", caller=self.char1)
        self.assertTrue(Job.objects.filter(bucket__name="Builds").exists())

    def test_jobs_work_out_of_character(self):
        """Jobs are on the account cmdset; an Account caller files and reads its own job."""
        keys = AccountCmdSet()
        keys.at_cmdset_creation()
        names = keys.get_all_cmd_keys_and_aliases()
        for name in ("jobs", "job", "myjobs", "job/submit", "buckets"):
            self.assertIn(name, names)
        chars = CharacterCmdSet()
        chars.at_cmdset_creation()
        self.assertNotIn("job/submit", chars.get_all_cmd_keys_and_aliases())

        self.call(CmdJobSubmit(), "Requests From OOC = hello", caller=self.account2)
        job = Job.objects.get(title="From OOC")
        self.assertEqual(job.creator, self.account2)
        out = self.call(CmdJobView(), job.ref, caller=self.account2)
        self.assertIn("From OOC", out)


class HuntStaffedJobTests(EvenniaCommandTest):
    """R-1: the merge-resolved +hunt/staffed path."""

    def test_staffed_hunt_opens_a_hunt_scenes_job(self):
        self.char1.predator_type = "Alleycat"
        out = self.call(CmdHunt(), "/staffed slum", caller=self.char1)
        job = Job.objects.get(bucket__name="Hunt Scenes")
        self.assertEqual(job.priority, "MEDIUM")
        self.assertIn(self.account, job.players.all())
        self.assertIn("slum", job.title)
        self.assertIn("Hunting pool:", job.description)
        self.assertIn(f"Job Hunt Scenes/{job.sequence_number}", out)
        self.assertIn(f"+job Hunt Scenes/{job.sequence_number}", out)

        player = _make_player(self)
        out = self.call(CmdJobView(), f"Hunt Scenes/{job.sequence_number}", caller=player)
        self.assertIn("not found", out)


class TorporTests(EvenniaCommandTest):
    def test_view_and_end(self):
        out = self.call(CmdTorpor(), "Char2", caller=self.char1)
        self.assertIn("not in torpor", out)
        self.char2.torpor = {"reason": "Failed to rise", "time": 0}
        out = self.call(CmdTorpor(), "Char2", caller=self.char1)
        self.assertIn("in torpor: Failed to rise", out)
        out = self.call(CmdTorpor(), "/end Char2", caller=self.char1)
        self.assertIn("has ended", out)
        self.assertIsNone(self.char2.torpor)

    def test_damage_torpor_is_reported(self):
        self.char2.set_damage("health", superficial=0, aggravated=self.char2.health_max)
        out = self.call(CmdTorpor(), "Char2", caller=self.char1)
        self.assertIn("full of Aggravated damage", out)

    def test_players_cant_use_it(self):
        player = _make_player(self)
        self.assertFalse(CmdTorpor().access(player, "cmd"))


class NPCTests(EvenniaCommandTest):
    def test_create_npc_builders_can_puppet_and_edit(self):
        out = self.call(CmdNPC(), "/create Old Tom", caller=self.char1)
        self.assertIn("Created NPC Old Tom", out)
        npc = self.char1.search("Old Tom")
        self.assertEqual(npc.splat, "mortal")
        self.assertEqual(npc.location, self.char1.location)
        self.assertIsNone(npc.account)
        self.assertIsNone(npc.bio)

        builder = self.account2
        builder.permissions.remove("Developer")
        builder.permissions.add("Builder")
        for access in ("puppet", "edit", "control", "delete"):
            self.assertTrue(npc.access(builder, access), access)
        builder.permissions.remove("Builder")
        self.assertFalse(npc.access(builder, "puppet"))

    def test_splat_option_and_validation(self):
        self.call(CmdNPC(), "/create Marguerite=ghoul", caller=self.char1)
        self.assertEqual(self.char1.search("Marguerite").splat, "ghoul")
        out = self.call(CmdNPC(), "/create Bad=werewolf", caller=self.char1)
        self.assertIn("Splat must be one of", out)

    def test_players_cant_use_it(self):
        player = _make_player(self)
        self.assertFalse(CmdNPC().access(player, "cmd"))


class NoDiceTests(EvenniaCommandTest):
    """Keep the hunt test from rolling: +hunt/staffed rolls nothing."""

    def test_staffed_hunt_rolls_nothing(self):
        with patch("dice.dice_roller.randint", side_effect=AssertionError("rolled")):
            self.call(CmdHunt(), "/staffed slum", caller=self.char1)
