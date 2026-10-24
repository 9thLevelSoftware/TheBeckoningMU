"""Canonical and historical effects on real Evennia Attribute wrappers."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB
from evennia.utils.dbserialize import deserialize
from evennia.utils.test_resources import EvenniaCommandTest

from commands.v5.effects import CmdEffects
from commands.v5.utils import discipline_effects, discipline_utils, thin_blood_utils
from dice.commands import CmdPower, CmdRoll


class EffectsStaffAuthorityTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.account.permissions.remove("Developer")
        self.account.permissions.add("Admin")
        self.char1.permissions.remove("Developer")
        self.char1.permissions.add("Player")
        self.account.is_superuser = False
        self.account.save(update_fields=["is_superuser"])

    def seed_effect(self):
        self.char1.db.active_effects = [
            discipline_effects.make_effect(
                effect_id="staff-test-blink",
                source_kind="discipline",
                power="Blink",
                discipline="Celerity",
                duration="turn",
                parameters={},
                applied="test",
                turns_remaining=1,
            )
        ]
        self.char1.db.fleetness_defense_used = True

    def assert_switches_denied_without_mutation(self):
        for args in ("/tick", "/clear staff-test-blink", "/clear all"):
            with self.subTest(command=args):
                self.seed_effect()
                before = deserialize(self.char1.db.active_effects)
                output = self.call(CmdEffects(), args, caller=self.char1)
                self.assertIn("Only staff", output)
                self.assertEqual(deserialize(self.char1.db.active_effects), before)
                self.assertIs(self.char1.db.fleetness_defense_used, True)

    def test_admin_account_authorizes_player_puppet_tick_and_clear(self):
        self.assertFalse(self.char1.check_permstring("Builder"))
        self.seed_effect()
        self.assertIn("Effect tick complete", self.call(CmdEffects(), "/tick", caller=self.char1))
        self.assertEqual(list(self.char1.db.active_effects), [])
        self.assertIs(self.char1.db.fleetness_defense_used, False)
        for args in ("/clear staff-test-blink", "/clear all"):
            with self.subTest(command=args):
                self.seed_effect()
                output = self.call(CmdEffects(), args, caller=self.char1)
                self.assertNotIn("Only staff", output)
                self.assertEqual(list(self.char1.db.active_effects), [])
                # Clear is not a new combat turn.
                self.assertIs(self.char1.db.fleetness_defense_used, True)

    def test_quell_uses_minimum_account_and_puppet_authority(self):
        self.account.attributes.add("_quell", True)
        self.assert_switches_denied_without_mutation()
        self.char1.permissions.add("Builder")
        self.seed_effect()
        self.assertIn("Effect tick complete", self.call(CmdEffects(), "/tick", caller=self.char1))
        # A high-ranked puppet cannot elevate its player account, even unquelled.
        ObjectDB.objects.filter(pk=self.char1.pk).update(db_account_id=self.account2.pk)
        self.assert_switches_denied_without_mutation()

    def test_fresh_authority_denies_warmed_external_revocation(self):
        self.char1.permissions.add("Builder")
        for revoked in ("permissions", "superuser", "active"):
            with self.subTest(revoked=revoked):
                self.account.permissions.add("Admin")
                AccountDB.objects.filter(pk=self.account.pk).update(
                    is_active=True, is_superuser=revoked != "permissions"
                )
                self.account.refresh_from_db()
                self.account.permissions.all()
                if revoked in ("permissions", "superuser"):
                    self.account.db_tags.through.objects.filter(
                        accountdb_id=self.account.pk, tag__db_tagtype="permission"
                    ).delete()
                if revoked == "superuser":
                    AccountDB.objects.filter(pk=self.account.pk).update(is_superuser=False)
                elif revoked == "active":
                    AccountDB.objects.filter(pk=self.account.pk).update(is_active=False)
                self.assert_switches_denied_without_mutation()


class EffectLifecycleTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char = self.char1  # Staff may explicitly clear and tick effects.
        self.char.hunger = 1

    def reload_effects(self):
        attr = self.char.attributes.get("active_effects", return_obj=True)
        attr.refresh_from_db()
        attr.flush_from_cache(force=True)
        self.char.attributes.reset_cache()
        return self.char.db.active_effects

    def test_one_record_per_real_activation_with_canonical_parameters(self):
        self.char.set_trait("Auspex", 1)
        self.char.learn_power("Heightened Senses")
        self.call(CmdPower(), "Heightened Senses", caller=self.char)
        effects = self.reload_effects()
        self.assertEqual(len(effects), 1)
        effect = effects[0]
        self.assertEqual(effect["schema_version"], 1)
        self.assertEqual(effect["activation_id"], effect["id"])
        self.assertEqual(discipline_effects.effect_parameters(effect)["perception_bonus"], 2)

    def test_haze_has_stable_id_displays_and_removes_only_itself(self):
        self.char.clan = "Thin-Blood"
        self.char.db.crafted_formulae = [{"name": "Haze"}]
        other = discipline_effects.apply_effect(self.char, {"name": "Awe", "discipline": "Presence"}, "scene")
        result = thin_blood_utils.use_alchemy(self.char, "Haze")
        self.assertTrue(result["success"])
        haze = discipline_effects.has_active_effect(self.char, "Haze")
        self.assertIsNotNone(haze)
        self.assertEqual(haze["source_kind"], "alchemy")
        haze_id = haze["id"]
        self.reload_effects()
        self.assertEqual(discipline_effects.has_active_effect(self.char, "Haze")["id"], haze_id)
        self.assertIn("Haze", self.call(CmdEffects(), "", caller=self.char))
        self.call(CmdEffects(), f"/clear {haze_id}", caller=self.char)
        self.assertEqual([e["id"] for e in self.char.db.active_effects], [other["id"]])

    def test_instant_alchemy_does_not_leave_lasting_record(self):
        # Use an actual offered instant formula, rather than a fake catalog entry.
        formula = next(f for f in thin_blood_utils.all_formulas() if f["duration_text"] == "instant")
        self.char.db.crafted_formulae = [{"name": formula["name"]}]
        with patch("random.randint", return_value=8):
            result = thin_blood_utils.use_alchemy(self.char, formula["name"])
        self.assertTrue(result["success"])
        self.assertEqual(list(self.char.db.active_effects), [])

    def test_normalization_is_pure_then_explicit_and_idempotent(self):
        self.char.db.active_effects = [
            {"type": "alchemy", "name": "Haze", "duration": "scene", "custom": {"keep": [1]}},
            {
                "id": "keep-id",
                "power": "Resilience",
                "discipline": "Fortitude",
                "duration": "scene",
                "damage_reduction": 2,
                "unknown_note": "retain",
            },
        ]
        before = deserialize(self.char.db.active_effects)
        dry = discipline_effects.normalize_effects(self.char)
        self.assertEqual(deserialize(self.char.db.active_effects), before)
        self.assertFalse(dry["records"][0].get("id"))
        self.assertEqual(dry["records"][0]["power"], "Haze")
        self.assertEqual(discipline_effects.effect_parameters(dry["records"][1])["damage_reduction"], 2)
        applied = discipline_effects.normalize_effects(self.char, persist=True)
        self.assertTrue(applied["records"][0]["id"])
        self.assertEqual(applied["records"][1]["id"], "keep-id")
        self.assertEqual(applied["records"][0]["custom"], {"keep": [1]})
        self.assertEqual(applied["records"][1]["unknown_note"], "retain")
        self.reload_effects()
        again = discipline_effects.normalize_effects(self.char, persist=True)
        self.assertEqual(again["changes"], [])
        self.assertEqual(again["records"], applied["records"])

    def test_unknown_malformed_and_duplicate_records_survive_safe_display_removal(self):
        unknown = {"schema_version": 99, "id": "future", "custom": "preserve", "parameters": {"damage_bonus": 99}}
        self.char.db.active_effects = [
            "old opaque value",
            unknown,
            {"id": "one", "power": "Awe", "discipline": "Presence", "duration": "scene", "applied": "old time"},
            {"id": "duplicate", "name": "Uncatalogued", "parameters": None},
            {"id": "duplicate", "name": "Another unknown"},
        ]
        before = deserialize(self.char.db.active_effects)
        report = discipline_effects.normalize_effects(self.char)
        self.assertTrue(report["unresolved"])
        self.assertEqual(discipline_effects.effect_parameters(unknown), {})
        self.assertIn("Awe", self.call(CmdEffects(), "", caller=self.char))
        self.assertFalse(discipline_effects.remove_effect(self.char, "missing"))
        self.assertFalse(discipline_effects.remove_effect(self.char, "duplicate"))
        self.assertTrue(discipline_effects.remove_effect(self.char, "one"))
        self.assertEqual(deserialize(self.char.db.active_effects), before[:2] + before[3:])

    def test_tick_after_reload_expires_only_valid_turn_effect(self):
        self.char.set_trait("Celerity", 3)
        self.char.learn_power("Blink")
        with patch("random.randint", return_value=8):
            result = discipline_utils.activate_discipline_power(self.char, "Celerity", "Blink")
        self.char.db.active_effects.append({"id": "bad-turn", "duration": "turn", "turns_remaining": "unknown"})
        self.reload_effects()
        expired = discipline_effects.tick_effects(self.char)
        self.assertEqual([e["id"] for e in expired], result["effect_ids"])
        self.assertEqual(self.char.db.active_effects[0]["id"], "bad-turn")

    def test_failed_willpower_reroll_removes_only_its_activation(self):
        self.char.set_trait("Presence", 3)
        self.char.learn_power("Dread Gaze")
        self.char.set_trait("Charisma", 3)
        self.char.hunger = 1
        self.char.blood_potency = 0
        other = discipline_effects.apply_effect(self.char, {"name": "Awe", "discipline": "Presence"}, "scene")
        with patch("random.randint", side_effect=[2, 2, 8, 2, 2, 2, 2, 2, 7]):
            self.call(CmdPower(), "Dread Gaze = Char2", caller=self.char)
        ids = self.char.ndb.last_roll["effect_ids"]
        self.assertEqual(len(ids), 1)
        self.reload_effects()
        with patch("random.randint", return_value=2):
            self.call(CmdRoll(), "/willpower 8", caller=self.char)
        self.assertEqual([e["id"] for e in self.char.db.active_effects], [other["id"]])

    def test_verified_instant_leftovers_retire_only_by_explicit_request(self):
        formula = next(f for f in thin_blood_utils.all_formulas() if f["duration_text"] == "instant")
        self.char.db.active_effects = [
            {"type": "alchemy", "name": formula["name"], "duration": "instant"},
            {"name": "Uncatalogued", "duration": "instant", "keep": True},
        ]
        before = deserialize(self.char.db.active_effects)
        discipline_effects.normalize_effects(self.char)
        self.assertEqual(deserialize(self.char.db.active_effects), before)
        report = discipline_effects.normalize_effects(self.char, persist=True, retire_instant=True)
        self.assertEqual(len(report["retired"]), 1)
        self.assertEqual(len(self.char.db.active_effects), 1)
        self.assertTrue(self.char.db.active_effects[0]["keep"])

    def test_management_command_dry_run_and_explicit_offline_persistence(self):
        from django.core.management.base import CommandError

        self.char.db.active_effects = [{"type": "alchemy", "name": "Haze", "duration": "scene"}]
        before = deserialize(self.char.db.active_effects)
        call_command("normalize_active_effects", character=[self.char.pk], stdout=StringIO())
        self.assertEqual(deserialize(self.char.db.active_effects), before)
        with self.assertRaises(CommandError):
            call_command("normalize_active_effects", character=[self.char.pk], apply=True, stdout=StringIO())
        call_command("normalize_active_effects", character=[self.char.pk], apply=True, offline=True, stdout=StringIO())
        self.assertTrue(self.char.db.active_effects[0]["id"])

    def test_opaque_store_unknown_turns_and_dynamic_duration_never_expire_automatically(self):
        self.char.db.active_effects = {"opaque": "retain"}
        self.assertIn("Unrecognized", self.call(CmdEffects(), "", caller=self.char))
        self.assertEqual(discipline_effects.tick_effects(self.char), [])
        self.assertFalse(discipline_effects.remove_effect(self.char, "opaque"))
        self.assertEqual(deserialize(self.char.db.active_effects), {"opaque": "retain"})
        discipline_effects.apply_effect(self.char, {"name": "Awe", "discipline": "Presence"}, "scene")
        self.assertEqual(deserialize(self.char.db.active_effects[0]), {"opaque": "retain"})
        self.char.db.active_effects = [
            {"name": "Uncatalogued", "duration": "turn", "turns_remaining": 1},
            {"type": "alchemy", "name": "Counterfeit", "duration": "instant"},
        ]
        discipline_effects.tick_effects(self.char)
        report = discipline_effects.normalize_effects(self.char, persist=True, retire_instant=True)
        self.assertEqual(report["retired"], [])
        self.assertEqual(len(self.char.db.active_effects), 2)

    def test_future_schema_and_duplicate_ids_are_not_rewritten_or_mechanically_applied(self):
        future = {"schema_version": 99, "id": ["opaque-id"], "extra": "retain"}
        self.char.db.active_effects = [
            future,
            {
                "id": "same",
                "power": "Resilience",
                "discipline": "Fortitude",
                "duration": "scene",
                "damage_reduction": 2,
            },
            {
                "id": "same",
                "power": "Resilience",
                "discipline": "Fortitude",
                "duration": "scene",
                "damage_reduction": 2,
            },
        ]
        discipline_effects.normalize_effects(self.char, persist=True)
        self.assertEqual(deserialize(self.char.db.active_effects[0]), future)
        for effect in discipline_effects.get_active_effects(self.char):
            self.assertEqual(discipline_effects.effect_parameters(effect), {})

    def test_unhashable_legacy_durations_display_normalize_and_tick_without_data_loss(self):
        for duration in (["unknown", "duration"], {"duration": "unresolved"}):
            with self.subTest(duration=duration):
                self.char.db.active_effects = [
                    {
                        "id": "malformed-duration",
                        "power": "Awe",
                        "discipline": "Presence",
                        "duration": duration,
                        "parameters": {"attraction": True},
                        "unknown_metadata": {"preserve": [1, 2]},
                    }
                ]
                before = deserialize(self.char.db.active_effects)
                self.assertIn("Awe", self.call(CmdEffects(), "", caller=self.char))
                report = discipline_effects.normalize_effects(self.char)
                self.assertTrue(any("duration" in item["reason"].lower() for item in report["unresolved"]))
                self.assertEqual(discipline_effects.effect_parameters(report["records"][0]), {})
                self.assertEqual(discipline_effects.tick_effects(self.char), [])
                self.assertEqual(deserialize(self.char.db.active_effects), before)
                discipline_effects.normalize_effects(self.char, persist=True)
                normalized = deserialize(self.char.db.active_effects)
                for key, value in before[0].items():
                    self.assertEqual(normalized[0][key], value)
                self.assertEqual(discipline_effects.tick_effects(self.char), [])
                self.assertEqual(deserialize(self.char.db.active_effects), normalized)

    def test_duplicate_turn_ids_remain_unticked_before_and_after_explicit_normalization(self):
        for persist in (False, True):
            with self.subTest(persist=persist):
                self.char.db.active_effects = [
                    {
                        "id": "duplicate-blink",
                        "power": "Blink",
                        "discipline": "Celerity",
                        "duration": "turn",
                        "turns_remaining": turns,
                        "custom": f"retain-{turns}",
                    }
                    for turns in (1, 2)
                ] + [
                    {
                        "id": "unique-blink",
                        "power": "Blink",
                        "discipline": "Celerity",
                        "duration": "turn",
                        "turns_remaining": 1,
                    }
                ]
                report = discipline_effects.normalize_effects(self.char, persist=persist)
                self.assertTrue(any("Duplicate effect ID" in item["reason"] for item in report["unresolved"]))
                before = deserialize(self.char.db.active_effects)
                expired = discipline_effects.tick_effects(self.char)
                self.assertEqual([effect["id"] for effect in expired], ["unique-blink"])
                self.assertEqual(deserialize(self.char.db.active_effects), before[:2])
