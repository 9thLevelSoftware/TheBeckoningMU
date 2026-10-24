"""Approved room policies exercised at their movement and hunting consumers."""

from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from evennia import create_object
from evennia.utils.test_resources import EvenniaTest

from world.room_rules import haven_context, hunting_context, is_day, room_access


class RoomAccessTests(EvenniaTest):
    def test_chronicle_clock_boundaries_and_timezone(self):
        for hour, minute, expected in ((5, 59, False), (6, 0, True), (17, 59, True), (18, 0, False)):
            local = datetime(2026, 10, 23, hour, minute, tzinfo=ZoneInfo("America/New_York"))
            self.assertEqual(is_day(local), expected)
            self.assertEqual(is_day(local.astimezone(ZoneInfo("UTC"))), expected)
        with self.assertRaises(ValueError):
            is_day(datetime(2026, 10, 23, 6))

    def test_each_splat_obeys_day_and_night_without_staff_bypass(self):
        for splat in ("vampire", "ghoul", "mortal"):
            self.char1.splat = splat
            for mode in ("always", "day_only", "night_only"):
                self.room2.db.day_night = mode
                for hour in (6, 18):
                    at = datetime(2026, 10, 23, hour, tzinfo=ZoneInfo("America/New_York"))
                    allowed, reason = room_access(self.char1, self.room2, at)
                    self.assertEqual(allowed, mode == "always" or (mode == "day_only") == (hour == 6))
                    self.assertEqual(bool(reason), not allowed)

    def test_restricted_requires_valid_character_allowlist(self):
        self.room2.db.day_night = "restricted"
        for invalid in (None, [], [True], [str(self.char1.id)], [self.char1.id, self.char1.id], {"id": self.char1.id}):
            self.room2.db.restricted_characters = invalid
            self.assertFalse(room_access(self.char1, self.room2)[0])
        self.room2.db.restricted_characters = [self.char1.id]
        self.assertTrue(room_access(self.char1, self.room2)[0])
        self.assertFalse(room_access(self.char2, self.room2)[0])
        self.room2.db.day_night = "legacy_unknown"
        self.assertFalse(room_access(self.char1, self.room2)[0])

    def test_exit_preserves_locks_and_applies_destination_policy(self):
        exit_obj = create_object(
            "typeclasses.exits.Exit", key="policy exit", location=self.room1, destination=self.room2
        )
        self.char1.msg = Mock()
        self.room2.db.day_night = "restricted"
        self.room2.db.restricted_characters = [self.char1.id]
        with patch.object(exit_obj, "access", return_value=False):
            exit_obj.at_traverse(self.char1, self.room2)
        self.assertEqual(self.char1.location, self.room1)
        self.room2.db.restricted_characters = [self.char2.id]
        with patch.object(exit_obj, "access", return_value=True):
            exit_obj.at_traverse(self.char1, self.room2)
        self.assertEqual(self.char1.location, self.room1)
        self.room2.db.restricted_characters = [self.char1.id]
        with patch.object(exit_obj, "access", return_value=True):
            exit_obj.at_traverse(self.char1, self.room2)
        self.assertEqual(self.char1.location, self.room2)

    def test_trigger_uses_same_chronicle_clock(self):
        from web.builder.v5_conditions import check_condition

        with patch("world.room_rules.is_day", return_value=False):
            self.assertTrue(check_condition("time_of_day", {"time": "night"}))
            self.assertFalse(check_condition("time_of_day", {"time": "day"}))


class RoomHuntingTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char1.predator_type = "Alleycat"
        self.char1.hunger = 5
        self.char1.set_trait("Strength", 3)
        self.char1.set_trait("Brawl", 3)

    def test_modifier_applies_to_each_ground_once_and_floors_at_one(self):
        self.room1.db.hunting_modifier = 3
        self.assertEqual(hunting_context(self.char1, "slum")["difficulty"], 1)
        self.assertEqual(hunting_context(self.char1, "wealthy")["difficulty"], 3)
        self.assertEqual(hunting_context(self.char1, "wealthy")["difficulty"], 3)
        self.room1.db.hunting_modifier = -2
        self.assertEqual(hunting_context(self.char1, "downtown")["difficulty"], 6)

    def test_real_hunt_and_snapshot_use_actual_room_difficulty(self):
        from commands.v5.hunt import CmdHunt
        from commands.v5.utils.hunting_utils import format_hunt_outcome

        self.room1.db.hunting_modifier = 2
        command = CmdHunt()
        command.caller = self.char1
        with patch("dice.dice_roller.randint", return_value=8) as dice:
            result = command._resolve_story_hunt("wealthy")
        self.assertEqual(result["difficulty"], 4)
        self.assertEqual(result["modifiers"]["room"]["difficulty_adjustment"], -2)
        self.assertEqual(dice.call_count, 6)
        self.assertEqual(result["hunger_after"], 3)
        self.assertIn("Room hunting modifier: +2", format_hunt_outcome(result))
        self.assertIsNotNone(self.char1.last_hunt)

    def test_absent_properties_are_compatible_and_invalid_modifier_is_explicit(self):
        self.assertEqual(hunting_context(self.char1, "downtown")["difficulty"], 4)
        self.room1.db.hunting_modifier = "ambiguous"
        context = hunting_context(self.char1, "downtown")
        self.assertEqual(context["difficulty"], 4)
        self.assertTrue(context["warning"])
        self.assertEqual(self.room1.db.hunting_modifier, "ambiguous")


class HavenRulesTests(EvenniaTest):
    def test_each_rating_has_an_explicit_adjudicated_action_without_bonus(self):
        self.room1.db.location_type = "haven"
        for field in ("security", "size", "luxury", "warding"):
            self.room1.attributes.add("haven_" + field, 2)
        self.room1.db.haven_location_hidden = True
        for action in ("intrusion", "space", "comfort", "occult", "concealment"):
            context = haven_context(self.room1, self.char1, action)
            self.assertEqual(context["status"], "staff_adjudication_required")
            self.assertEqual(context["automatic_modifiers"], [])
            self.assertEqual(context["ratings"]["security"], 2)
            self.assertTrue(context["location_hidden"])
        with self.assertRaises(ValueError):
            haven_context(self.room1, self.char1, "invented_auto_win")
        self.assertIn("staff-adjudicated", self.room1.get_display_desc(self.char1))

    def test_staff_inspection_includes_all_facts_and_player_cannot_invoke_it(self):
        from commands.v5.staff import CmdRoomRules

        self.room1.db.location_type = "haven"
        self.char1.msg = Mock()
        command = CmdRoomRules()
        command.caller = self.char1
        command.args = ""
        command.lhs = ""
        command.rhs = None
        command.switches = []
        with patch("dice.commands._is_staff", return_value=False):
            command.func()
        self.assertIn("staff", str(self.char1.msg.call_args).lower())
        with patch("dice.commands._is_staff", return_value=True):
            command.func()
        shown = str(self.char1.msg.call_args)
        for value in ("America/New_York", "security", "size", "luxury", "warding", "staff-adjudicated"):
            self.assertIn(value, shown)
