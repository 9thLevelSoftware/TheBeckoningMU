"""Deterministic hunt feedback survives prose delivery failures and retries."""

import json
from unittest.mock import Mock, patch

from evennia.utils.test_resources import EvenniaTest
from twisted.internet.defer import Deferred

from commands.v5.hunt import CmdHunt
from commands.v5.utils import hunting_utils
from narrative.models import NarrativeConsent, StorySession
from traits.models import CharacterBio


class HuntPresentationTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.character = self.char1
        self.character.predator_type = "Alleycat"
        self.character.hunger = 5
        self.character.set_trait("Strength", 4)
        self.character.set_trait("Brawl", 3)
        CharacterBio.objects.create(character=self.character, account=self.character.account, status="approved")
        NarrativeConsent.objects.create(character=self.character, account=self.character.account, opted_in=True)
        self.character.msg = Mock()

    def story(self, args):
        command = CmdHunt()
        command.caller = self.character
        command.args = args
        command._story_hunt()

    def messages(self):
        return "\n".join(str(call.args[0]) for call in self.character.msg.call_args_list)

    def test_stored_json_has_original_dice_flags_and_modifier_breakdown(self):
        self.character.set_damage("health", superficial=self.character.health_max)
        with patch("dice.dice_roller.randint", return_value=10):
            command = CmdHunt()
            command.caller = self.character
            snapshot = command._resolve_story_hunt("downtown")
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)
        self.assertEqual(snapshot["pool"]["base"], 7)
        self.assertEqual(snapshot["pool"]["rolled"], 5)
        self.assertEqual(snapshot["modifiers"]["net_dice"], -2)
        self.assertIn("impaired", snapshot["pool"]["breakdown"])
        self.assertEqual(snapshot["dice"]["hunger"], [10] * 5)
        self.assertTrue(snapshot["outcome"]["is_messy_critical"])
        self.assertEqual(snapshot["hunger_before"], 5)
        self.assertEqual(snapshot["hunger_after"], 3)
        self.assertEqual(snapshot["hunger_reduction"], 2)
        self.assertTrue(snapshot["resonance"])
        self.assertTrue(snapshot["complications"])

    def test_result_shown_before_dispatch_and_async_errors_do_not_repeat_it(self):
        for error in (RuntimeError("HTTP 503"), ValueError("Malformed response"), TimeoutError("Timed out")):
            with self.subTest(error=str(error)):
                StorySession.objects.all().delete()
                self.character.hunger = 5
                self.character.last_hunt = None
                self.character.msg.reset_mock()
                deferred = Deferred()

                def dispatch(session, action, deferred=deferred):
                    text = self.messages()
                    for expected in ("SUCCESSFUL HUNT", "Hunger 5 -> 3", "Resonance:", "Complication:", "Hunger dice:"):
                        self.assertIn(expected, text)
                    return Deferred() if deferred.called else deferred

                with (
                    patch("narrative.services.configured_provider", return_value=object()),
                    patch("narrative.services.generate_story", side_effect=dispatch),
                    patch("dice.dice_roller.randint", return_value=10) as dice,
                ):
                    self.story("start downtown")
                    hunger, cooldown = self.character.hunger, self.character.last_hunt
                    deferred.errback(error)
                    self.story("start downtown")
                    self.story("resume I wait.")
                self.assertEqual(dice.call_count, 7)
                self.assertEqual(self.character.hunger, hunger)
                self.assertEqual(self.character.last_hunt, cooldown)
                self.assertEqual(self.messages().count("SUCCESSFUL HUNT"), 1)
                self.assertIn("story request failed", self.messages())

    def test_sync_error_keeps_result_and_success_only_adds_prose(self):
        with (
            patch("narrative.services.configured_provider", return_value=object()),
            patch("narrative.services.generate_story", side_effect=RuntimeError("Provider unavailable")),
            patch("dice.dice_roller.randint", return_value=10),
        ):
            self.story("start downtown")
        self.assertIn("Hunger 5 -> 3", self.messages())
        self.assertIn("Provider unavailable", self.messages())
        self.assertEqual(self.messages().count("SUCCESSFUL HUNT"), 1)
        deferred = Deferred()
        with (
            patch("narrative.services.configured_provider", return_value=object()),
            patch("narrative.services.generate_story", return_value=deferred),
            patch("dice.dice_roller.randint", side_effect=AssertionError("Unexpected reroll")),
        ):
            self.story("resume I wait.")
            deferred.callback("The street is quiet.")
        self.assertEqual(self.messages().count("SUCCESSFUL HUNT"), 1)
        self.assertIn("[AI-generated narrative]", self.messages())

    def test_status_without_provider_or_consent_reads_only_authorized_saved_result(self):
        session = StorySession.objects.create(
            character=self.character,
            deterministic_outcome={
                "hunting_success": False,
                "location": "slum",
                "hunger_before": 4,
                "hunger_after": 4,
                "hunger_reduction": 0,
                "resonance": None,
                "complications": [],
            },
        )
        NarrativeConsent.objects.filter(character=self.character).update(opted_in=False)
        with (
            patch("narrative.services.configured_provider", side_effect=AssertionError("Provider inspected")),
            patch("narrative.services.generate_story", side_effect=AssertionError("Request dispatched")),
            patch("commands.v5.hunt.hunt", side_effect=AssertionError("Unexpected hunt")),
        ):
            self.story("status")
        self.assertIn("HUNT FAILED", self.messages())
        self.assertIn("Hunger 4 -> 4", self.messages())
        self.assertIn("Original dice unavailable", self.messages())
        session.refresh_from_db()
        self.assertEqual(session.deterministic_outcome["hunger_after"], 4)
        CharacterBio.objects.filter(character=self.character).update(account=self.account2)
        self.character.msg.reset_mock()
        self.story("status")
        self.assertIn("owning account", self.messages())
        self.assertNotIn("HUNT FAILED", self.messages())

    def test_failed_hunt_records_unchanged_hunger_and_bestial_flags(self):
        with patch("dice.dice_roller.randint", return_value=1):
            command = CmdHunt()
            command.caller = self.character
            snapshot = command._resolve_story_hunt("wealthy")
        self.assertEqual(snapshot["hunger_before"], 5)
        self.assertEqual(snapshot["hunger_after"], 5)
        self.assertEqual(snapshot["hunger_reduction"], 0)
        self.assertTrue(snapshot["outcome"]["is_bestial_failure"])
        self.assertFalse(snapshot["hunting_success"])
        self.assertTrue(snapshot["complications"])
        text = hunting_utils.format_hunt_outcome(snapshot)
        self.assertIn("BESTIAL FAILURE", text)
        self.assertIn("No resonance gained", text)

    def test_ordinary_hunt_uses_the_same_snapshot_formatter(self):
        command = CmdHunt()
        command.caller = self.character
        command.switches = []
        command.lhs = "downtown"
        command.rhs = None
        with (
            patch("dice.dice_roller.randint", return_value=8),
            patch("commands.v5.hunt.format_hunt_outcome", wraps=hunting_utils.format_hunt_outcome) as formatter,
        ):
            command.func()
        snapshot = formatter.call_args.args[0]
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["hunger_after"], self.character.hunger)
        self.assertEqual(snapshot["dice"]["regular"], [8, 8])
        self.assertEqual(snapshot["dice"]["hunger"], [8] * 5)
        self.assertIn("Hunger 5 -> 3", self.messages())
