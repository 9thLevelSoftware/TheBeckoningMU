"""Complete advancement on real Evennia objects; no live database fixtures."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.utils.dbserialize import deserialize
from evennia.utils.test_resources import EvenniaCommandTest

from commands.v5.utils import xp_utils
from commands.v5.xp import CmdSpend
from dice.commands import CmdPower
from tests.chargen_fixtures import legal_payload
from traits.models import CharacterBio


class AdvancementCompletionTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.clan = "Brujah"
        self.char.set_trait("Potence", 1)
        self.char.learn_power("Lethal Body")
        self.char.db.experience = {"total_earned": 20, "total_spent": 0, "log": []}

    def test_selected_power_is_immediately_usable_from_commands(self):
        out = self.call(CmdSpend(), "discipline Potence = Prowess", caller=self.char)
        self.assertIn("Prowess", out)
        self.assertEqual((self.char.get_trait("Potence"), self.char.xp), (2, 10))
        self.assertEqual(self.char.known_powers, ["Lethal Body", "Prowess"])
        with patch("random.randint", return_value=8):
            self.call(CmdPower(), "Prowess", caller=self.char)
        self.assertTrue(any(e.get("power") == "Prowess" for e in self.char.db.active_effects))

    def test_missing_wrong_duplicate_unknown_and_overlevel_choices_change_nothing(self):
        for choice in (None, "Heightened Senses", "Lethal Body", "Fireball", "Fist of Caine"):
            with self.subTest(choice=choice):
                before = self.char.snapshot_sheet()
                with self.assertRaises(ValueError):
                    self.char.spend_xp("Potence", "discipline", choice)
                self.assertEqual(self.char.snapshot_sheet(), before)
        out = self.call(CmdSpend(), "discipline Potence", caller=self.char)
        self.assertIn("Prowess", out)
        self.assertIn("Nothing was spent", out)

    def test_amalgam_is_checked_before_mutation(self):
        self.char.set_trait("Potence", 2)
        self.char.db.experience["total_earned"] = 50
        before = self.char.snapshot_sheet()
        with self.assertRaisesRegex(ValueError, "Presence 3"):
            self.char.spend_xp("Potence", "discipline", "Spark of Rage")
        self.assertEqual(self.char.snapshot_sheet(), before)
        self.char.set_trait("Presence", 3)
        self.char.spend_xp("Potence", "discipline", "Spark of Rage")
        self.assertIn("Spark of Rage", self.char.known_powers)

    def test_cost_quote_does_not_require_power_choice(self):
        before = self.char.snapshot_sheet()
        self.assertEqual(self.char.xp_spend_cost("Potence", "discipline")["cost"], 10)
        self.assertEqual(xp_utils.get_xp_cost_discipline(self.char, "Potence"), (10, 2, True))
        self.assertEqual(self.char.snapshot_sheet(), before)

    def test_bare_int_discipline_survives_purchase(self):
        self.char.db.stats["disciplines"]["potence"] = 1
        self.char.spend_xp("Potence", "discipline", "Prowess")
        self.assertEqual(self.char.get_trait("Potence"), 2)
        self.assertEqual(self.char.known_powers, ["Prowess"])

    def assert_failed_write_preserves_sheet(self, action):
        before = self.char.snapshot_sheet()
        original_add = self.char.attributes.add
        count = 0

        def fail_after_write(*args, **kwargs):
            nonlocal count
            result = original_add(*args, **kwargs)
            count += 1
            if count == 1:
                raise RuntimeError("injected after first Attribute write")
            return result

        with (
            patch.object(self.char.attributes, "add", side_effect=fail_after_write),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            action()
        self.assertEqual(self.char.snapshot_sheet(), before)
        # Evict the object and its Attribute idmapper entries for an independent read.
        for attr in self.char.db_attributes.all():
            attr.flush_from_cache(force=True)
        self.char.flush_from_cache(force=True)
        fresh = ObjectDB.objects.get(pk=self.char.pk)
        self.assertIsNot(fresh, self.char)
        self.assertEqual(fresh.snapshot_sheet(), before)

    def test_purchase_failure_restores_database_and_existing_caches(self):
        self.assert_failed_write_preserves_sheet(lambda: self.char.spend_xp("Potence", "discipline", "Prowess"))

    def legacy_purchase(self):
        """A retained, valid creation grant plus a verified old dot-only XP spend."""
        from world.rules_chargen import apply_chargen, parse_submission

        self.char.reset_sheet()
        sub = parse_submission(legal_payload())
        apply_chargen(self.char, sub)
        CharacterBio.objects.create(
            character=self.char, account=self.account2, status="approved", submission=sub.as_dict()
        )
        self.char.set_trait("Potence", 3)
        self.char.db.experience = {
            "total_earned": 50,
            "total_spent": 15,
            "log": [
                {"type": "award", "amount": 50, "reason": "Staff award", "balance": 50},
                {"type": "spend", "amount": -15, "reason": "Raised Potence to 3 (in-clan)", "balance": 35},
            ],
        }

    def issue_choice(self):
        from traits.power_reconciliation import reconcile_discipline_powers

        self.legacy_purchase()
        report = reconcile_discipline_powers(self.char, apply=True)
        self.assertEqual(len(report["created"]), 1)
        return report["created"][0]["id"]

    def test_reconciliation_dry_run_apply_and_repeat_preserve_xp_history(self):
        from traits.power_reconciliation import reconcile_discipline_powers

        self.legacy_purchase()
        before = self.char.snapshot_sheet()
        dry = reconcile_discipline_powers(self.char)
        self.assertEqual(len(dry["proposed"]), 1)
        self.assertEqual(self.char.snapshot_sheet(), before)
        applied = reconcile_discipline_powers(self.char, apply=True)
        self.assertEqual(applied["created"], dry["proposed"])
        again = reconcile_discipline_powers(self.char, apply=True)
        self.assertEqual(again["created"], [])
        exp = deserialize(self.char.db.experience)
        self.assertEqual({key: exp[key] for key in before["experience"]}, before["experience"])
        self.assertEqual(
            self.char.known_powers,
            before["stats"]["disciplines"]["potence"]["powers"]
            + before["stats"]["disciplines"]["presence"]["powers"]
            + before["stats"]["disciplines"]["celerity"]["powers"],
        )

    def test_unproven_deficit_requires_staff_review(self):
        from traits.power_reconciliation import reconcile_discipline_powers

        self.char.set_trait("Potence", 2)
        before = self.char.snapshot_sheet()
        report = reconcile_discipline_powers(self.char, apply=True)
        self.assertEqual(report["created"], [])
        self.assertTrue(report["review"])
        self.assertEqual(self.char.snapshot_sheet(), before)

    def test_choice_claim_is_free_and_repeat_safe(self):
        entitlement = self.issue_choice()
        before = deserialize(self.char.db.experience)
        out = self.call(CmdSpend(), "/choices", caller=self.char)
        self.assertIn(entitlement, out)
        out = self.call(CmdSpend(), f"/claim {entitlement} = Brutal Feed", caller=self.char)
        self.assertIn("Brutal Feed", out)
        self.assertEqual(self.char.xp, 35)
        self.assertEqual(self.char.known_powers.count("Brutal Feed"), 1)
        again = self.char.claim_discipline_power(entitlement, "Brutal Feed")
        self.assertTrue(again["already_claimed"])
        with self.assertRaises(ValueError):
            self.char.claim_discipline_power(entitlement, "Uncanny Grip")
        self.assertEqual(self.char.xp, 35)
        for key in ("total_earned", "total_spent", "log"):
            self.assertEqual(self.char.db.experience[key], before[key])

    def test_invalid_claim_and_failure_restore_both_stores(self):
        entitlement = self.issue_choice()
        before = self.char.snapshot_sheet()
        for power in ("Spark of Rage", "Prowess", "Heightened Senses", "Fist of Caine"):
            with self.subTest(power=power), self.assertRaises(ValueError):
                self.char.claim_discipline_power(entitlement, power)
            self.assertEqual(self.char.snapshot_sheet(), before)
        self.assert_failed_write_preserves_sheet(lambda: self.char.claim_discipline_power(entitlement, "Brutal Feed"))

    def test_snapshot_reset_restore_preserves_entitlements(self):
        entitlement = self.issue_choice()
        before = self.char.snapshot_sheet()
        self.char.reset_sheet()
        self.assertEqual(self.char.pending_power_choices, ())
        self.char.restore_sheet(before)
        self.assertEqual(self.char.pending_power_choices[0]["id"], entitlement)

    def test_revoked_resubmission_retains_choices_and_rejected_replacement_clears_them(self):
        from traits.utils import resubmit_revoked_unit, resubmit_unit
        from world.rules_chargen import parse_submission

        entitlement = self.issue_choice()
        bio = self.char.bio
        bio.status = "revoked"
        bio.save(update_fields=["status"])
        before = self.char.snapshot_sheet()
        resubmit_revoked_unit(bio.pk, self.account2, {"concept": "Revised narrative"})
        self.assertEqual(self.char.snapshot_sheet(), before)
        self.assertEqual(self.char.pending_power_choices[0]["id"], entitlement)
        bio.refresh_from_db()
        bio.status = "rejected"
        bio.save(update_fields=["status"])
        resubmit_unit(bio.pk, self.account2, parse_submission(legal_payload()))
        self.assertEqual(self.char.pending_power_choices, ())

    def test_corrupt_history_and_removed_creation_powers_cannot_issue_choices(self):
        from traits.power_reconciliation import reconcile_discipline_powers

        self.legacy_purchase()
        baseline = self.char.snapshot_sheet()
        for mutate in (
            lambda: self.char.db.experience.__setitem__("total_spent", 14),
            lambda: self.char.db.experience["log"][1].__setitem__("amount", -10),
            lambda: self.char.db.stats["disciplines"]["potence"]["powers"].remove("Lethal Body"),
            lambda: self.char.db.stats["disciplines"]["potence"]["powers"].append("Unknown Power"),
        ):
            self.char.restore_sheet(baseline)
            mutate()
            before = self.char.snapshot_sheet()
            report = reconcile_discipline_powers(self.char, apply=True)
            self.assertEqual(report["created"], [])
            self.assertTrue(report["review"])
            self.assertEqual(self.char.snapshot_sheet(), before)

    def test_consumed_entitlement_is_never_reissued_after_staff_removes_power(self):
        from traits.power_reconciliation import reconcile_discipline_powers

        entitlement = self.issue_choice()
        self.char.claim_discipline_power(entitlement, "Brutal Feed")
        self.char.db.stats["disciplines"]["potence"]["powers"].remove("Brutal Feed")
        before = self.char.snapshot_sheet()
        report = reconcile_discipline_powers(self.char, apply=True)
        self.assertEqual(report["created"], [])
        self.assertTrue(report["review"])
        self.char.claim_discipline_power(entitlement, "Brutal Feed")
        self.assertEqual(self.char.snapshot_sheet(), before)

    def test_claim_cannot_exceed_historical_entitlement_rating(self):
        entitlement = self.issue_choice()
        self.char.set_trait("Potence", 4)
        before = self.char.snapshot_sheet()
        with self.assertRaises(ValueError):
            self.char.claim_discipline_power(entitlement, "Draught of Might")
        self.assertEqual(self.char.snapshot_sheet(), before)

    def test_management_apply_requires_offline_and_is_idempotent(self):
        from django.core.management.base import CommandError

        self.legacy_purchase()
        with self.assertRaises(CommandError):
            call_command("reconcile_discipline_powers", character=[self.char.pk], apply=True, stdout=StringIO())
        for _ in range(2):
            call_command(
                "reconcile_discipline_powers", character=[self.char.pk], apply=True, offline=True, stdout=StringIO()
            )
        self.assertEqual(len(self.char.pending_power_choices), 1)

    def test_management_command_defaults_to_inventory(self):
        self.legacy_purchase()
        before = self.char.snapshot_sheet()
        output = StringIO()
        call_command("reconcile_discipline_powers", character=[self.char.pk], stdout=output)
        self.assertIn("potence", output.getvalue().lower())
        self.assertEqual(self.char.snapshot_sheet(), before)
