"""Durable ritual lifecycle with injected clock, real Attributes and no sleeps."""

import json
from contextlib import contextmanager
from unittest.mock import patch

from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from commands.v5.utils.discipline_effects import perform_ritual, tick_effects
from world.v5_data import DISCIPLINES


class RitualCastingTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.caster, self.staff = self.char2, self.char1
        self.caster.set_trait("Blood Sorcery", 5)
        self.caster.set_trait("Intelligence", 3)
        self.caster.blood_potency = 0
        self.caster.hunger = 0
        self.caster.learn_ritual("Blood Walk")

    @property
    def api(self):
        from world.rituals import casting

        return casting

    def procedure(self, *, timing="before_casting", opposed="none", checkpoints=None):
        return {
            "materials": "Storyteller witnessed the required materials and preparation",
            "target_facts": "Storyteller verified the requested subject/object facts",
            "duration": "staff_adjudicated",
            "outcome": "Storyteller determines the permitted result",
            "failure": "Casting fails; paid Rouse checks remain paid, no information or effect granted",
            "failure_policy": "no_effect_retain_paid",
            "cancellation": "retain_paid",
            "payment_timing": timing,
            "casting_start": {
                "before_casting": "after_payment",
                "after_casting": "on_confirm",
                "staged_preparation": "after_checkpoints",
            }[timing],
            "opposition": opposed,
            "opposed_ties": "defender_wins",
            "opposed_success": "catalog_difficulty_and_contest",
            "casting_relationship": "The catalog casting time starts after all preparation payments",
            "checkpoints": checkpoints or [],
        }

    def begin(self, name="Blood Walk", target=None):
        with (
            patch.object(self.api, "current_time", return_value=1000),
            patch.object(self.api.RitualCastingScript, "start"),
        ):
            plan = self.api.prepare_cast(self.caster, name, target=target)
            cast_id = self.api.begin_cast(self.caster, plan)
        return cast_id

    def attest(self, cast_id, procedure=None):
        state = self.api.cast_status(self.caster, cast_id)
        return self.api.attest_cast(
            self.caster, cast_id, self.staff, revision=state["revision"], procedure=procedure or self.procedure()
        )

    def confirm(self, cast_id, die=8):
        with patch.object(self.api, "current_time", return_value=1000), patch("random.randint", return_value=die):
            return self.api.confirm_cast(self.caster, cast_id)

    def resolve(self, cast_id, die=8):
        with patch.object(self.api, "current_time", return_value=100000), patch("random.randint", return_value=die):
            return self.api.resolve_cast(self.caster, cast_id)

    def fresh_script(self, cast_id):
        script = self.api.script_for_cast(self.caster, cast_id)
        for attr in script.db_attributes.all():
            attr.flush_from_cache(force=True)
        script.flush_from_cache(force=True)
        return ScriptDB.objects.get(pk=script.pk)

    def test_staff_command_uses_admin_account_for_player_puppet_and_honors_quell(self):
        from commands.v5.rituals import CmdRitual

        self.account.permissions.remove("Developer")
        self.account.permissions.add("Admin")
        self.staff.permissions.remove("Developer")
        self.staff.permissions.add("Player")
        self.account.is_superuser = False
        self.account.save(update_fields=["is_superuser"])
        cast_id = self.begin()
        command = f"/attest {self.caster.key}/{cast_id} = 0/{json.dumps(self.procedure())}"
        output = self.call(CmdRitual(), command, caller=self.staff)
        self.assertIn("prepared (revision 1)", output)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "prepared")

        self.account.attributes.add("_quell", True)
        second = self.begin()
        before = self.api.cast_status(self.caster, second)
        output = self.call(CmdRitual(), command.replace(cast_id, second), caller=self.staff)
        self.assertIn("Ritual refused", output)
        self.assertEqual(self.api.cast_status(self.caster, second), before)
        self.assertEqual(self.caster.hunger, 0)
        self.assertEqual(list(self.caster.db.active_effects), [])

    def test_all_offered_rituals_have_explicit_execution_metadata(self):
        rituals = DISCIPLINES["Blood Sorcery"]["rituals"]
        self.assertEqual(len(rituals), 26)
        for ritual in rituals:
            with self.subTest(ritual=ritual["name"]):
                execution = ritual["execution"]
                self.assertEqual(execution["casting_seconds"], ritual["level"] * 300)
                self.assertEqual(execution["rouse"], ritual["rouse"])
                self.assertEqual(execution["dice_pool"], ritual["dice_pool"])
                self.assertEqual(execution["opposed_by"], ritual.get("opposed_by"))
                self.assertEqual(execution["outcome"], "staff_adjudicated")
                self.assertEqual(execution["duration"], "staff_attested")

    def test_placeholder_cannot_grant_an_unlearned_ritual_or_generic_success(self):
        result = perform_ritual(self.caster, "Firewalker", ingredients=["staff says yes"])
        self.assertFalse(result["success"])
        self.assertEqual(list(self.caster.db.active_effects), [])

    def test_invalid_prepare_refuses_without_payment_or_persistence(self):
        before = (self.caster.hunger, ScriptDB.objects.count())
        for name, target in (("Unknown Rite", None), ("Firewalker", None), ("Blood Walk", "fake-target")):
            with self.subTest(name=name, target=target), self.assertRaises(ValueError):
                self.api.prepare_cast(self.caster, name, target=target)
        self.caster.set_trait("Blood Sorcery", 0)
        with self.assertRaises(ValueError):
            self.api.prepare_cast(self.caster, "Blood Walk")
        self.assertEqual((self.caster.hunger, ScriptDB.objects.count()), before)

    def test_begin_is_unpaid_and_repeat_safe_and_requires_staff_attestation(self):
        with patch.object(self.api.RitualCastingScript, "start"):
            plan = self.api.prepare_cast(self.caster, "Blood Walk")
            cast_id = self.api.begin_cast(self.caster, plan)
            self.assertEqual(self.api.begin_cast(self.caster, plan), cast_id)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "awaiting_attestation")
        with self.assertRaises(ValueError):
            self.api.confirm_cast(self.caster, cast_id)
        self.assertEqual(self.caster.hunger, 0)

    def test_staff_spoof_stale_revision_and_incomplete_attestation_are_refused(self):
        cast_id = self.begin()
        for staff in (self.caster, {"id": self.staff.pk, "is_staff": True}):
            with self.subTest(staff=staff), self.assertRaises(ValueError):
                self.api.attest_cast(self.caster, cast_id, staff, revision=0, procedure=self.procedure())
        incomplete = self.procedure()
        del incomplete["materials"]
        with self.assertRaises(ValueError):
            self.attest(cast_id, incomplete)
        self.attest(cast_id)
        with self.assertRaises(ValueError):
            self.api.attest_cast(self.caster, cast_id, self.staff, revision=0, procedure=self.procedure())
        self.assertEqual(self.caster.hunger, 0)

    def test_paid_failure_consumes_cost_once_and_duplicate_completion_preserves_result(self):
        cast_id = self.begin()
        self.attest(cast_id)
        self.confirm(cast_id, die=2)
        self.assertEqual(self.caster.hunger, 1)
        state = self.resolve(cast_id, die=2)
        self.assertEqual(state["phase"], "failed")
        self.assertFalse(state["result"]["casting_success"])
        self.assertEqual(len(state["payments"]), 1)
        with patch("random.randint", side_effect=AssertionError("must not roll again")):
            self.assertEqual(self.api.resolve_cast(self.caster, cast_id), state)
        self.assertEqual(self.caster.hunger, 1)
        self.assertEqual(list(self.caster.db.active_effects), [])

    def test_after_casting_payment_uses_pre_rouse_hunger_and_no_power_reroll_bonus(self):
        cast_id = self.begin()
        self.attest(cast_id, self.procedure(timing="after_casting"))
        self.confirm(cast_id)
        self.assertEqual(self.caster.hunger, 0)
        with patch.object(self.api, "current_time", return_value=100000), patch("random.randint", return_value=2):
            state = self.api.resolve_cast(self.caster, cast_id)
        self.assertEqual(state["result"]["roll"]["hunger"], [])
        self.assertEqual(self.caster.hunger, 1)
        self.assertEqual(len(state["payments"][0]["checks"]), 1)

    def test_cancellation_before_payment_and_while_casting_has_recorded_cost_policy(self):
        unpaid = self.begin()
        self.assertEqual(self.api.cancel_cast(self.caster, unpaid)["phase"], "cancelled")
        self.assertEqual(self.caster.hunger, 0)
        paid = self.begin()
        self.attest(paid)
        self.confirm(paid, die=2)
        self.api.cancel_cast(self.caster, paid)
        self.assertEqual(self.caster.hunger, 1)
        self.assertEqual(self.resolve(paid)["phase"], "cancelled")

    def test_restart_waiting_resumes_deadline_without_recharging(self):
        cast_id = self.begin()
        self.attest(cast_id)
        self.confirm(cast_id)
        script = self.fresh_script(cast_id)
        with (
            patch.object(self.api, "current_time", return_value=1100),
            patch("random.randint", side_effect=AssertionError("not due")),
        ):
            script.at_start()
            script.at_repeat()
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "casting")
        with patch.object(self.api, "current_time", return_value=1300), patch("random.randint", return_value=8):
            script.at_repeat()
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "awaiting_adjudication")
        self.assertEqual(len(self.api.cast_status(self.caster, cast_id)["payments"]), 1)

    def test_payment_settlement_failure_rolls_back_resources_but_preserves_indeterminate_claim(self):
        cast_id = self.begin()
        self.attest(cast_id)
        original_save = self.api._save_state

        def fail_settlement(script, state):
            if state["phase"] == "casting":
                raise RuntimeError("injected settlement failure")
            return original_save(script, state)

        with (
            patch.object(self.api, "_save_state", side_effect=fail_settlement),
            self.assertRaisesRegex(RuntimeError, "settlement"),
            patch("random.randint", return_value=2),
        ):
            self.confirm(cast_id, die=2)
        self.assertEqual(self.caster.hunger, 0)
        self.caster.flush_from_cache(force=True)
        fresh = ObjectDB.objects.get(pk=self.caster.pk)
        fresh.attributes.reset_cache()
        self.assertEqual(fresh.hunger, 0)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "payment_in_progress")
        with patch("random.randint", side_effect=AssertionError("no retry")):
            self.fresh_script(cast_id).at_start()
            self.api.resolve_cast(self.caster, cast_id)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "review_required")

    def test_interrupted_resolution_is_review_required_and_never_rolled_again(self):
        cast_id = self.begin()
        self.attest(cast_id)
        self.confirm(cast_id)
        original_save = self.api._save_state

        def fail_result(script, state):
            if state["phase"] == "awaiting_adjudication":
                raise RuntimeError("injected after roll")
            return original_save(script, state)

        with patch.object(self.api, "_save_state", side_effect=fail_result), self.assertRaises(RuntimeError):
            self.resolve(cast_id)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "resolving")
        with patch("random.randint", side_effect=AssertionError("no retry")):
            self.fresh_script(cast_id).at_start()
            self.api.resolve_cast(self.caster, cast_id)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "review_required")

    def test_target_loss_fails_closed_without_extra_payment_or_roll(self):
        target = create.create_object("typeclasses.objects.Object", key="Ritual fixture target")
        cast_id = self.begin(target=target)
        self.attest(cast_id)
        self.confirm(cast_id)
        target.delete()
        with patch("random.randint", side_effect=AssertionError("target gone")):
            state = self.resolve(cast_id)
        self.assertEqual(state["phase"], "failed")
        self.assertIn("target", state["result"]["reason"].lower())

    def test_success_waits_for_authenticated_adjudication_before_descriptive_effect(self):
        cast_id = self.begin()
        self.attest(cast_id)
        self.confirm(cast_id)
        state = self.resolve(cast_id)
        self.assertEqual(state["phase"], "awaiting_adjudication")
        self.assertTrue(state["result"]["adjudication_required"])
        self.assertEqual(list(self.caster.db.active_effects), [])
        kwargs = {
            "revision": state["revision"],
            "outcome": "Staff records only the adjudicated outcome",
            "duration": {"kind": "turn", "turns": 1},
        }
        with self.assertRaises(ValueError):
            self.api.adjudicate_cast(self.caster, cast_id, self.caster, **kwargs)
        result = self.api.adjudicate_cast(self.caster, cast_id, self.staff, **kwargs)
        self.api.adjudicate_cast(self.caster, cast_id, self.staff, **kwargs)
        self.assertEqual(result["phase"], "completed")
        self.assertEqual(len(self.caster.db.active_effects), 1)
        self.assertEqual(self.caster.db.active_effects[0]["id"], f"ritual:{cast_id}:outcome")
        self.assertTrue(self.caster.db.active_effects[0]["parameters"]["adjudication_only"])
        self.assertEqual(len(tick_effects(self.caster)), 1)

    def test_sanctuary_requires_twelve_identified_explicit_preparation_payments(self):
        self.caster.learn_ritual("Escape to True Sanctuary")
        cast_id = self.begin("Escape to True Sanctuary")
        checkpoints = [
            {"id": f"prep-{i}", "rouse": 1, "description": f"Staff verified preparation checkpoint {i}"}
            for i in range(1, 13)
        ]
        self.attest(cast_id, self.procedure(timing="staged_preparation", checkpoints=checkpoints))
        self.assertEqual(self.confirm(cast_id)["phase"], "preparing")
        self.assertEqual(self.caster.hunger, 0)
        with patch("random.randint", return_value=8), patch.object(self.api, "current_time", return_value=1000):
            for checkpoint in checkpoints:
                state = self.api.cast_status(self.caster, cast_id)
                self.api.pay_preparation(self.caster, cast_id, self.staff, checkpoint["id"], revision=state["revision"])
            with patch("random.randint", side_effect=AssertionError("duplicate step")):
                self.api.pay_preparation(self.caster, cast_id, self.staff, "prep-1", revision=0)
        state = self.api.cast_status(self.caster, cast_id)
        self.assertEqual((len(state["payments"]), state["phase"], state["ready_at"]), (12, "casting", 2500))
        self.assertTrue(all(len(payment["checks"]) == 1 for payment in state["payments"]))

    def test_catalog_opposition_override_is_preserved_and_tie_policy_is_attested(self):
        self.caster.learn_ritual("Truth of Blood")
        self.caster.set_trait("Resolve", 3)
        self.staff.set_trait("Composure", 3)
        self.staff.set_trait("Occult", 5)
        cast_id = self.begin("Truth of Blood", target=self.staff)
        self.attest(cast_id, self.procedure(opposed="catalog_roll"))
        self.confirm(cast_id)
        state = self.resolve(cast_id)
        self.assertEqual(state["result"]["roll"]["pool_text"], "Resolve + Blood Sorcery")
        self.assertEqual(state["result"]["defense"]["pool_text"], "Composure + Occult")
        self.assertFalse(state["result"]["casting_success"])  # 8 vs 8, attested defender wins ties.

    def test_hunger_five_refuses_before_claim_and_multicheck_payment_retains_pending_frenzy(self):
        self.caster.learn_ritual("Warding Circle against Ghouls")
        cast_id = self.begin("Warding Circle against Ghouls")
        self.attest(cast_id)
        self.caster.hunger = 5
        before = self.api.cast_status(self.caster, cast_id)
        with (
            patch("random.randint", side_effect=AssertionError("no voluntary Rouse at five")),
            self.assertRaises(ValueError),
        ):
            self.api.confirm_cast(self.caster, cast_id)
        self.assertEqual(self.api.cast_status(self.caster, cast_id), before)
        self.caster.hunger = 4
        paid = self.confirm(cast_id, die=2)
        self.assertEqual(len(paid["payments"][0]["checks"]), 3)
        self.assertEqual(self.caster.hunger, 5)
        self.assertEqual(self.caster.db.pending_frenzy_test["count"], 2)

    def test_adjudication_failure_rolls_back_marker_and_requires_restart_review(self):
        cast_id = self.begin()
        self.attest(cast_id)
        self.confirm(cast_id)
        state = self.resolve(cast_id)
        original = self.api._save_state

        def fail_marker_settlement(script, record):
            if record["phase"] == "completed":
                raise RuntimeError("injected marker settlement failure")
            return original(script, record)

        with patch.object(self.api, "_save_state", side_effect=fail_marker_settlement), self.assertRaises(RuntimeError):
            self.api.adjudicate_cast(
                self.caster,
                cast_id,
                self.staff,
                revision=state["revision"],
                outcome="Explicitly adjudicated marker",
                duration={"kind": "scene"},
            )
        self.assertEqual(list(self.caster.db.active_effects), [])
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "adjudicating")
        self.fresh_script(cast_id).at_start()
        reviewed = self.api.cast_status(self.caster, cast_id)
        with self.assertRaises(ValueError):
            self.api.close_review(self.caster, cast_id, self.caster, revision=reviewed["revision"], note="spoof")
        closed = self.api.close_review(
            self.caster,
            cast_id,
            self.staff,
            revision=reviewed["revision"],
            note="Investigated interrupted transaction; abandoning without replay or refund",
        )
        self.assertEqual(closed["phase"], "cancelled")
        self.assertEqual(len(closed["operations"]), 3)
        self.assertEqual(list(self.caster.db.active_effects), [])

    def test_player_and_staff_commands_follow_unpaid_attested_lifecycle(self):
        import json

        from commands.v5.rituals import CmdRitual

        with patch.object(self.api.RitualCastingScript, "start"):
            output = self.call(CmdRitual(), "Blood Walk", caller=self.caster)
        self.assertIn("Unpaid request", output)
        state = self.api.list_casts(self.caster)[0]
        cast_id = state["cast_id"]
        refused = self.call(
            CmdRitual(), f"/attest Char2/{cast_id}=0/{json.dumps(self.procedure())}", caller=self.caster
        )
        self.assertIn("Current persisted Builder authority is required", refused)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "awaiting_attestation")
        self.assertEqual(self.caster.hunger, 0)
        output = self.call(CmdRitual(), f"/attest Char2/{cast_id}=0/{json.dumps(self.procedure())}", caller=self.staff)
        self.assertIn("prepared", output)
        with patch.object(self.api, "current_time", return_value=1000), patch("random.randint", return_value=8):
            self.call(CmdRitual(), f"/confirm {cast_id}", caller=self.caster)
        with patch.object(self.api, "current_time", return_value=1300), patch("random.randint", return_value=8):
            output = self.call(CmdRitual(), f"/resolve {cast_id}", caller=self.caster)
        self.assertIn("No facts or powers were granted", output)

    def test_opposed_cast_requires_explicit_success_procedure_instead_of_a_silent_combination(self):
        self.caster.learn_ritual("Truth of Blood")
        cast_id = self.begin("Truth of Blood", target=self.staff)
        procedure = self.procedure(opposed="catalog_roll")
        procedure.pop("opposed_success", None)
        with self.assertRaisesRegex(ValueError, "opposed success"):
            self.attest(cast_id, procedure)
        self.assertEqual(self.api.cast_status(self.caster, cast_id)["phase"], "awaiting_attestation")
        self.assertEqual(self.caster.hunger, 0)
        procedure["opposed_success"] = "catalog_difficulty_and_contest"
        self.attest(cast_id, procedure)
        self.confirm(cast_id)
        state = self.resolve(cast_id)
        self.assertEqual(state["phase"], "awaiting_adjudication")
        self.assertTrue(state["result"]["adjudication_required"])

    def test_terminal_timer_stops_without_deleting_history_and_pending_adjudication_keeps_recovery(self):
        cast_id = self.begin()
        self.attest(cast_id)
        self.confirm(cast_id)
        waiting = self.resolve(cast_id)
        script = self.api.script_for_cast(self.caster, cast_id)
        with (
            patch.object(script, "stop", wraps=script.stop) as stop,
            patch.object(self.api, "cast_status", side_effect=AssertionError("idle timer must not lock/write status")),
        ):
            script.at_repeat()
            stop.assert_not_called()  # A future adjudication claim still needs restart recovery ownership.
        self.assertEqual(self.api.cast_status(self.caster, cast_id), waiting)
        completed = self.api.adjudicate_cast(
            self.caster,
            cast_id,
            self.staff,
            revision=waiting["revision"],
            outcome="Explicit adjudicated outcome",
            duration={"kind": "instant"},
        )
        with (
            patch.object(script, "stop", wraps=script.stop) as stop,
            patch.object(
                self.api, "cast_status", side_effect=AssertionError("terminal timer must not lock/write status")
            ),
        ):
            script.at_repeat()
            stop.assert_called_once()
        self.assertTrue(ScriptDB.objects.filter(pk=script.pk).exists())
        self.assertEqual(self.api.cast_status(self.caster, cast_id), completed)

    def assert_authority_refusal_preserves_cast(self, cast_id, actor):
        before = self.api.cast_status(self.caster, cast_id)
        sheet = self.caster.snapshot_sheet()
        with self.assertRaisesRegex(ValueError, "Builder|persisted|active"):
            self.api.attest_cast(self.caster, cast_id, actor, revision=before["revision"], procedure=self.procedure())
        self.assertEqual(self.api.cast_status(self.caster, cast_id), before)
        self.assertEqual(self.caster.snapshot_sheet(), sheet)
        self.assertEqual(list(self.caster.db.active_effects), [])

    def test_fresh_staff_authority_rejects_warmed_permission_revocation_at_locked_decision(self):
        cast_id = self.begin()
        self.assertTrue(self.staff.check_permstring("Builder"))
        self.account.permissions.all()  # Warm the handler that another process would not invalidate.
        locked = self.api._locked
        entries = 0

        @contextmanager
        def revoke_before_lock(script, caster):
            nonlocal entries
            entries += 1
            if entries == 2:  # First entry is the helper's read-only before snapshot.
                self.account.db_tags.through.objects.filter(
                    accountdb_id=self.account.pk, tag__db_tagtype="permission"
                ).delete()
            with locked(script, caster) as state:
                yield state

        # Old _staff runs before this guard; a safe decision checks persisted
        # authority only after entering the guarded state-transition unit.
        before = self.api.cast_status(self.caster, cast_id)
        with patch.object(self.api, "_locked", revoke_before_lock):
            self.assert_authority_refusal_preserves_cast(cast_id, self.staff)
        self.assertEqual(self.api.cast_status(self.caster, cast_id), before)

    def test_fresh_staff_authority_rejects_revoked_superuser_and_inactive_account(self):
        self.account.db_tags.through.objects.filter(accountdb_id=self.account.pk, tag__db_tagtype="permission").delete()
        for revoke in ("superuser", "active"):
            with self.subTest(revoke=revoke):
                AccountDB.objects.filter(pk=self.account.pk).update(is_superuser=True, is_active=True)
                self.account.refresh_from_db()
                self.account.attributes.add("_quell", False)
                self.assertTrue(self.account.check_permstring("Builder"))
                cast_id = self.begin()
                AccountDB.objects.filter(pk=self.account.pk).update(
                    **({"is_superuser": False} if revoke == "superuser" else {"is_active": False})
                )
                self.assert_authority_refusal_preserves_cast(cast_id, self.account)

    def test_staff_authority_rejects_unsaved_account_and_accepts_real_persisted_account_actor(self):
        cast_id = self.begin()
        fake = AccountDB(pk=9999999, username="Not persisted", is_superuser=True, is_active=True)
        self.assert_authority_refusal_preserves_cast(cast_id, fake)
        state = self.api.attest_cast(self.caster, cast_id, self.account, revision=0, procedure=self.procedure())
        self.assertEqual(state["phase"], "prepared")
        self.assertEqual(state["attestation"]["actor"]["kind"], "account")

    def test_staff_character_checks_persisted_account_binding_and_fresh_quell_permissions(self):
        cast_id = self.begin()
        self.assertTrue(self.staff.check_permstring("Builder"))
        ObjectDB.objects.filter(pk=self.staff.pk).update(db_account_id=self.account2.pk)
        self.assert_authority_refusal_preserves_cast(cast_id, self.staff)
        ObjectDB.objects.filter(pk=self.staff.pk).update(db_account_id=self.account.pk)
        self.account.attributes.add("_quell", True)
        self.staff.permissions.all()  # Keep the former Developer cached.
        self.staff.db_tags.through.objects.filter(objectdb_id=self.staff.pk, tag__db_tagtype="permission").delete()
        self.assert_authority_refusal_preserves_cast(cast_id, self.staff)

    def test_adjudication_preserves_opaque_scalar_effect_store(self):
        cast_id = self.begin()
        self.attest(cast_id)
        self.confirm(cast_id)
        state = self.resolve(cast_id)
        self.caster.db.active_effects = 7
        kwargs = {
            "revision": state["revision"],
            "outcome": "Explicit descriptive adjudication",
            "duration": {"kind": "scene"},
        }
        completed = self.api.adjudicate_cast(self.caster, cast_id, self.staff, **kwargs)
        self.assertEqual(completed["phase"], "completed")
        self.assertEqual(self.caster.db.active_effects[0], 7)
        self.assertEqual(self.caster.db.active_effects[1]["id"], f"ritual:{cast_id}:outcome")
        self.api.adjudicate_cast(self.caster, cast_id, self.staff, **kwargs)
        self.assertEqual(len(self.caster.db.active_effects), 2)
