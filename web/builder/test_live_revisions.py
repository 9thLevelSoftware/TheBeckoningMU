"""Reviewed replacement against exact live identities; no tag-derived authority."""

import copy
from unittest import mock

from django.urls import reverse
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB
from evennia.utils import create
from evennia.utils.idmapper.models import flush_cache

from web.builder import promotion, sandbox_builder
from web.builder.models import BuildProject
from web.builder.test_sandbox import SandboxTestBase, _timer_running, area_map


class LiveRevisionTests(SandboxTestBase):
    def setUp(self):
        self.addCleanup(flush_cache)
        super().setUp()

    def source(self, v5=None):
        data = area_map(3, timed_rooms=(1, 3))
        if v5:
            data["rooms"]["r1"]["v5"].update(v5)
        data["objects"] = {
            "f0": {"prototype_id": "wooden_chair", "prototype_revision": 1, "room_id": "r1"},
            "f2": {"prototype_id": "wooden_table", "prototype_revision": 1, "room_id": "r3"},
        }
        project = BuildProject.objects.create(
            user=self.owner,
            name="Live source",
            map_data=data,
            connection_room_id=self.plaza.pk,
            connection_direction="n",
        )
        project.submit()
        project.approve(self.builder2, project.version)
        sandbox_builder.build_unit(project.pk)
        promotion.promote_unit(project.pk)
        project.refresh_from_db()
        return project

    def candidate(self, source, modified=True):
        from web.builder.revisions import fork_replacement

        project = fork_replacement(source.pk, self.owner, source.version)
        if modified:
            data = project.map_data
            data["rooms"]["r1"]["name"] = "Reviewed replacement hall"
            data["rooms"].pop("r3")
            data["rooms"]["r4"] = {
                "name": "New annex",
                "description": "A reviewed addition.",
                "triggers": [
                    {
                        "id": "newtimer",
                        "type": "timed",
                        "interval": 60,
                        "action": "emit_message",
                        "parameters": {"message": "Tick"},
                    }
                ],
            }
            data["exits"].pop("e2a")
            data["exits"].pop("e2b")
            data["exits"]["e4a"] = {"source": "r2", "target": "r4", "name": "east"}
            data["exits"]["e4b"] = {"source": "r4", "target": "r2", "name": "west"}
            data["objects"]["f0"]["name"] = "Reviewed chair"
            data["objects"].pop("f2")
            data["objects"]["f1"] = {"prototype_id": "wooden_table", "prototype_revision": 1, "room_id": "r4"}
            project.save(update_fields=["map_data"])
        project.submit()
        project.approve(self.builder2, project.version)
        return project

    def execute(self, project, actor=None):
        from web.builder.live_replacement import replace_live_unit

        return replace_live_unit(project.pk, actor or self.owner, project.version)

    def test_each_addition_receipt_is_durable_before_the_next_world_step(self):
        from web.builder import live_replacement
        from web.builder.replacement_receipts import append_receipt

        source = self.source()
        project = self.candidate(source)
        observed = []

        def check_receipt(candidate, **receipt):
            append_receipt(candidate, **receipt)
            journal = BuildProject.objects.filter(pk=candidate.pk).values_list("replacement_journal", flat=True).get()
            if receipt.get("object_receipt"):
                item = receipt["object_receipt"]
                self.assertEqual(journal["created_object_ids"][-1], item["object_id"])
                self.assertEqual(journal["created_objects"][-1], item)
            else:
                self.assertEqual(journal["created_script_ids"][-1], receipt["script_id"])
            self.assertEqual(
                journal["saved_objects"][str(source.live_manifest["rooms"]["r1"]["object_id"])]["key"], "Room 1"
            )
            observed.append(receipt)

        with mock.patch.object(live_replacement, "append_receipt", side_effect=check_receipt, create=True):
            self.execute(project)
        self.assertEqual(len(observed), 5)  # Room, two exits, fixture, timer.

    def test_failed_compact_receipt_compensates_created_object_and_releases_claim(self):
        from web.builder import live_replacement
        from web.builder.replacement_receipts import ReceiptError

        source = self.source()
        project = self.candidate(source)
        before = set(ObjectDB.objects.values_list("pk", flat=True))
        with (
            mock.patch.object(
                live_replacement, "append_receipt", side_effect=ReceiptError("receipt failure"), create=True
            ),
            self.assertRaisesRegex(live_replacement.ReplacementError, "receipt failure"),
        ):
            self.execute(project)
        self.assertEqual(set(ObjectDB.objects.values_list("pk", flat=True)), before)
        project.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(project.status, "approved")
        self.assertEqual(project.replacement_journal["state"], "rolled_back")
        self.assertIsNone(source.replacement_claim_id)
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.execute(project)
        project.refresh_from_db()
        self.assertEqual(project.status, "live")

    def test_new_live_manifest_binds_current_lineage_exact_provenance_and_timers(self):
        source = self.source()
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.assertEqual(source.live_manifest["schema_version"], 2)
        self.assertEqual(len(source.live_manifest["scripts"]), 2)
        self.assertEqual(source.live_manifest["rooms"]["r1"]["provenance"]["project_id"], source.pk)

    def test_replacement_is_explicit_reviewed_diff_and_approval_does_not_change_source(self):
        source = self.source()
        old = copy.deepcopy(source.approved_map_data)
        project = self.candidate(source)
        self.assertEqual(project.revision_intent, "replacement")
        self.assertEqual(project.root_project_id, source.pk)
        plan = project.approved_map_data["replacement"]
        self.assertEqual(plan["target"]["project_id"], source.pk)
        self.assertIn("r4", plan["changes"]["rooms"]["additions"])
        self.assertIn("r3", plan["changes"]["rooms"]["retirements"])
        self.assertEqual(plan["changes"]["rooms"]["changes"]["r1"]["name"]["after"], "Reviewed replacement hall")
        source.refresh_from_db()
        self.assertEqual(source.approved_map_data, old)
        self.assertEqual(ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"]).key, "Room 1")
        review = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        item = next(item for item in review["reviewed"] if item["id"] == project.pk)
        self.assertEqual(item["revision_intent"], "replacement")

    def test_retained_ids_gameplay_attributes_and_unrelated_locks_are_preserved(self):
        source = self.source()
        project = self.candidate(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        room.db.played_state = {"visits": 17}
        room.locks.add("custom_scene:perm(Admin)")
        old_room_id = room.pk
        old_exit = source.live_manifest["exits"]["e1a"]["object_id"]
        old_fixture = source.live_manifest["fixtures"]["f0"]["object_id"]
        result = self.execute(project)
        project.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(project.status, "live")
        self.assertEqual(source.status, "superseded")
        self.assertEqual(source.current_live_revision_id, project.pk)
        self.assertEqual(project.live_manifest["rooms"]["r1"]["object_id"], old_room_id)
        self.assertEqual(project.live_manifest["exits"]["e1a"]["object_id"], old_exit)
        self.assertEqual(project.live_manifest["fixtures"]["f0"]["object_id"], old_fixture)
        self.assertEqual(room.key, "Reviewed replacement hall")
        self.assertEqual(dict(room.db.played_state), {"visits": 17})
        self.assertIn("perm(Admin)", room.locks.get("custom_scene"))
        self.assertEqual(result["status"], "live")

    def test_removed_objects_and_timers_are_retired_not_purged(self):
        source = self.source()
        old_room = source.live_manifest["rooms"]["r3"]["object_id"]
        old_exit = source.live_manifest["exits"]["e2a"]["object_id"]
        old_fixture = source.live_manifest["fixtures"]["f2"]["object_id"]
        old_timer = source.live_manifest["scripts"]["r3:drip3"]["script_id"]
        project = self.candidate(source)
        self.execute(project)
        for pk in (old_room, old_exit, old_fixture):
            obj = ObjectDB.objects.get(pk=pk)
            self.assertEqual(obj.db.builder_retired["replacement_project_id"], project.pk)
            self.assertIsNone(obj.db_location_id)
            self.assertIsNone(obj.db_destination_id)
        timer = ScriptDB.objects.get(pk=old_timer)
        self.assertFalse(_timer_running(timer))
        self.assertIsNone(timer.db_obj_id)
        project.refresh_from_db()
        self.assertIn(str(old_room), project.retired_manifest["objects"])

    def test_stale_source_or_candidate_version_refuses_without_mutating_world(self):
        from web.builder.live_replacement import ReplacementError, replace_live_unit

        source = self.source()
        project = self.candidate(source)
        before = set(ObjectDB.objects.values_list("id", flat=True))
        with self.assertRaises(ReplacementError):
            replace_live_unit(project.pk, self.owner, project.version + 1)
        BuildProject.objects.filter(pk=source.pk).update(version=source.version + 1)
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), before)

    def test_only_one_sibling_revision_can_win_and_success_cannot_replay(self):
        from web.builder.live_replacement import ReplacementError

        source = self.source()
        first = self.candidate(source)
        second = self.candidate(source, modified=False)
        self.execute(first)
        ids = set(ObjectDB.objects.values_list("id", flat=True))
        for candidate in (first, second):
            with self.assertRaises(ReplacementError):
                self.execute(candidate)
        self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), ids)
        self.assertEqual(BuildProject.objects.filter(status="live").count(), 1)

    def test_second_generation_can_replace_first_with_shared_root(self):
        source = self.source()
        first = self.candidate(source)
        self.execute(first)
        first.refresh_from_db()
        second = self.candidate(first, modified=False)
        self.execute(second)
        second.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(second.root_project_id, source.pk)
        self.assertEqual(source.current_live_revision_id, second.pk)
        self.assertEqual(BuildProject.objects.filter(status="live").count(), 1)

    def test_legacy_untrusted_live_manifest_and_nonowner_cannot_fork_replacement(self):
        from web.builder.revisions import RevisionError, fork_replacement

        source = self.source()
        with self.assertRaises(RevisionError):
            fork_replacement(source.pk, self.builder2, source.version)
        BuildProject.objects.filter(pk=source.pk).update(live_manifest={})
        with self.assertRaises(RevisionError):
            fork_replacement(source.pk, self.owner, source.version)

    def test_occupants_including_npcs_foreign_contents_and_exits_refuse(self):
        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        for typeclass in ("typeclasses.characters.Character", "typeclasses.objects.Object"):
            obj = create.create_object(typeclass, key="Unreviewed occupant", location=room)
            with self.assertRaises(ReplacementError):
                self.execute(project)
            obj.location = self.plaza
        foreign = create.create_object(
            "typeclasses.exits.Exit", key="Foreign exit", location=self.plaza, destination=room
        )
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertIsNotNone(foreign.pk)

    def test_moved_fixture_changed_type_or_provenance_refuses(self):
        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source)
        fixture = ObjectDB.objects.get(pk=source.live_manifest["fixtures"]["f0"]["object_id"])
        old_location = fixture.location
        fixture.location = self.plaza
        with self.assertRaises(ReplacementError):
            self.execute(project)
        fixture.location = old_location
        fixture.db.builder_fixture = {"project_id": source.pk}
        with self.assertRaises(ReplacementError):
            self.execute(project)
        room_id = source.live_manifest["rooms"]["r1"]["object_id"]
        ObjectDB.objects.filter(pk=room_id).update(db_typeclass_path="typeclasses.characters.Character")
        with self.assertRaises(ReplacementError):
            self.execute(project)

    def test_connection_change_is_reviewed_and_reuses_connector_identities(self):
        from web.builder.revisions import fork_replacement

        source = self.source()
        target = create.create_object("typeclasses.rooms.Room", key="New connection", nohome=True)
        project = fork_replacement(source.pk, self.owner, source.version)
        project.connection_room_id = target.pk
        project.connection_direction = "e"
        project.submit()
        project.approve(self.builder2, project.version)
        old_ids = [entry["object_id"] for entry in source.live_manifest["connection_exits"]]
        self.execute(project)
        project.refresh_from_db()
        self.assertEqual([entry["object_id"] for entry in project.live_manifest["connection_exits"]], old_ids)
        self.assertEqual(ObjectDB.objects.get(pk=old_ids[0]).db_location_id, target.pk)
        self.assertEqual(ObjectDB.objects.get(pk=old_ids[0]).key, "east")

    def assert_unclaimed(self, source, project, object_ids):
        source.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(project.status, "approved")
        self.assertEqual(project.replacement_journal, {})
        self.assertEqual(source.status, "live")
        root = BuildProject.objects.get(pk=source.root_project_id)
        self.assertEqual(root.current_live_revision_id, source.pk)
        self.assertIsNone(root.replacement_claim_id)
        self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), object_ids)

    def test_warmed_attribute_drift_is_refused_and_actual_values_preserved(self):
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle

        from web.builder.live_replacement import ReplacementError

        source = self.source(v5={"day_night": "restricted", "restricted_characters": [11]})
        project = self.candidate(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        fixture = ObjectDB.objects.get(pk=source.live_manifest["fixtures"]["f0"]["object_id"])
        script = ScriptDB.objects.get(pk=source.live_manifest["scripts"]["r1:drip1"]["script_id"])
        object_ids = set(ObjectDB.objects.values_list("id", flat=True))
        for obj, key, drift in (
            (room, "builder_revision", {"project_id": -1}),
            (room, "desc", "Changed outside the builder"),
            (room, "day_night", "night_only"),
            (room, "restricted_characters", [22]),
            (fixture, "builder_fixture", {"project_id": -1}),
            (fixture, "desc", "A different chair"),
            (script, "trigger_action", "send_message"),
            (script, "trigger_parameters", {"message": "External change"}),
            (script, "trigger_id", "external-trigger"),
        ):
            with self.subTest(key=key, object_id=obj.pk):
                attr = obj.attributes.get(key, return_obj=True)
                original = copy.deepcopy(attr.db_value)
                self.assertIsNotNone(obj.attributes.get(key))  # Warm both caches.
                Attribute.objects.filter(pk=attr.pk).update(db_value=to_pickle(drift))
                with self.assertRaises(ReplacementError):
                    self.execute(project)
                self.assertEqual(
                    Attribute.objects.filter(pk=attr.pk).values_list("db_value", flat=True).get(), to_pickle(drift)
                )
                self.assertEqual(obj.attributes.get(key), drift)
                self.assert_unclaimed(source, project, object_ids)
                Attribute.objects.filter(pk=attr.pk).update(db_value=original)
                attr.db_value = original
                obj.attributes.reset_cache()

    def test_warmed_timer_scalar_and_exit_alias_lock_drift_is_refused(self):
        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source)
        object_ids = set(ObjectDB.objects.values_list("id", flat=True))
        script = ScriptDB.objects.get(pk=source.live_manifest["scripts"]["r1:drip1"]["script_id"])
        original = script.db_interval
        ScriptDB.objects.filter(pk=script.pk).update(db_interval=original + 60)
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertEqual(
            ScriptDB.objects.filter(pk=script.pk).values_list("db_interval", flat=True).get(), original + 60
        )
        self.assertEqual(script.db_interval, original + 60)
        self.assert_unclaimed(source, project, object_ids)
        ScriptDB.objects.filter(pk=script.pk).update(db_interval=original)
        script.db_interval = original

        exit_obj = ObjectDB.objects.get(pk=source.live_manifest["exits"]["e1a"]["object_id"])
        alias = exit_obj.aliases.get("e", return_tagobj=True)
        self.assertEqual(exit_obj.aliases.all(), ["e"])
        type(alias).objects.filter(pk=alias.pk).update(db_key="changed-alias")
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertEqual(
            type(alias).objects.filter(pk=alias.pk).values_list("db_key", flat=True).get(), "changed-alias"
        )
        self.assertEqual(exit_obj.aliases.all(), ["changed-alias"])
        self.assert_unclaimed(source, project, object_ids)
        type(alias).objects.filter(pk=alias.pk).update(db_key="e")
        alias.db_key = "e"
        exit_obj.aliases.reset_cache()
        changed_lock = exit_obj.db_lock_storage + ";traverse:false()"
        ObjectDB.objects.filter(pk=exit_obj.pk).update(db_lock_storage=changed_lock)
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertEqual(
            ObjectDB.objects.filter(pk=exit_obj.pk).values_list("db_lock_storage", flat=True).get(), changed_lock
        )
        self.assert_unclaimed(source, project, object_ids)

    def test_before_state_uses_fresh_home_locks_and_timer_pause_values(self):
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle

        from web.builder import live_replacement

        source = self.source()
        project = self.candidate(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        script = ScriptDB.objects.get(pk=source.live_manifest["scripts"]["r1:drip1"]["script_id"])
        room.locks.all()
        changed_lock = room.db_lock_storage + ";custom_scene:perm(Admin)"
        ObjectDB.objects.filter(pk=room.pk).update(db_home_id=self.plaza.pk, db_lock_storage=changed_lock)
        script.db._paused_callcount = 3
        attr = script.attributes.get("_paused_callcount", return_obj=True)
        Attribute.objects.filter(pk=attr.pk).update(db_value=to_pickle(19))
        with (
            mock.patch.object(live_replacement, "_checkpoint", side_effect=RuntimeError("fresh journal boundary")),
            self.assertRaises(live_replacement.ReplacementError),
        ):
            self.execute(project)
        self.assertEqual(room.db_home_id, self.plaza.pk)
        self.assertEqual(room.db_lock_storage, changed_lock)
        self.assertEqual(
            ObjectDB.objects.filter(pk=room.pk).values_list("db_home_id", "db_lock_storage").get(),
            (self.plaza.pk, changed_lock),
        )
        project.refresh_from_db()
        self.assertEqual(
            project.replacement_journal["saved_scripts"][str(script.pk)]["attributes"]["_paused_callcount"]["value"], 19
        )
        self.assertEqual(project.replacement_journal["state"], "rolled_back")

    def test_warmed_account_authority_drift_refuses_without_claim(self):
        from evennia.accounts.models import AccountDB

        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source)
        object_ids = set(ObjectDB.objects.values_list("id", flat=True))
        self.assertTrue(self.owner.check_permstring("Builder"))
        AccountDB.objects.filter(pk=self.owner.pk).update(is_active=False)
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assert_unclaimed(source, project, object_ids)
        AccountDB.objects.filter(pk=self.owner.pk).update(is_active=True)
        through = AccountDB.db_tags.through
        through.objects.filter(accountdb_id=self.owner.pk).delete()
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assert_unclaimed(source, project, object_ids)
        self.owner.is_superuser = True
        AccountDB.objects.filter(pk=self.owner.pk).update(is_superuser=False)
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assert_unclaimed(source, project, object_ids)

    def test_authority_is_rechecked_inside_record_claim(self):
        from evennia.accounts.models import AccountDB

        from web.builder import live_replacement

        source = self.source()
        project = self.candidate(source)
        object_ids = set(ObjectDB.objects.values_list("id", flat=True))
        claim = live_replacement._claim

        def revoke_then_claim(*args, **kwargs):
            AccountDB.objects.filter(pk=self.owner.pk).update(is_active=False)
            return claim(*args, **kwargs)

        with (
            mock.patch.object(live_replacement, "_claim", side_effect=revoke_then_claim) as claimed,
            self.assertRaises(live_replacement.ReplacementError),
        ):
            self.execute(project)
        claimed.assert_called_once()
        self.assert_unclaimed(source, project, object_ids)

    def test_fresh_authority_preserves_admin_and_unquelled_superuser_policy(self):
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle

        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source, modified=False)
        self.execute(project, self.admin)  # A current nonowner Admin remains allowed.
        project.refresh_from_db()
        second = self.candidate(project, modified=False)
        self.admin.permissions.clear()
        self.admin.is_superuser = True
        self.admin.save(update_fields=["is_superuser"])
        self.admin.db._quell = False
        self.assertTrue(self.admin.check_permstring("Admin"))
        attr = self.admin.attributes.get("_quell", return_obj=True)
        Attribute.objects.filter(pk=attr.pk).update(db_value=to_pickle(True))
        object_ids = set(ObjectDB.objects.values_list("id", flat=True))
        with self.assertRaises(ReplacementError):
            self.execute(second, self.admin)
        self.assert_unclaimed(project, second, object_ids)
        Attribute.objects.filter(pk=attr.pk).update(db_value=to_pickle(False))
        self.execute(second, self.admin)
        second.refresh_from_db()
        self.assertEqual(second.status, "live")

    def test_warmed_attachment_type_tags_and_direction_are_checked_fresh(self):
        from evennia.typeclasses.tags import Tag

        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source)
        object_ids = set(ObjectDB.objects.values_list("id", flat=True))
        self.assertTrue(self.plaza.is_typeclass("typeclasses.rooms.Room", exact=False))
        ObjectDB.objects.filter(pk=self.plaza.pk).update(db_typeclass_path="typeclasses.characters.Character")
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertEqual(
            ObjectDB.objects.filter(pk=self.plaza.pk).values_list("db_typeclass_path", flat=True).get(),
            "typeclasses.characters.Character",
        )
        self.assert_unclaimed(source, project, object_ids)
        ObjectDB.objects.filter(pk=self.plaza.pk).update(db_typeclass_path="typeclasses.rooms.Room")

        self.assertFalse(self.plaza.tags.has("sandbox"))
        tag = Tag.objects.filter(db_key="sandbox", db_tagtype__isnull=True, db_model="objectdb").first()
        link = ObjectDB.db_tags.through.objects.create(objectdb_id=self.plaza.pk, tag_id=tag.pk)
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertTrue(ObjectDB.db_tags.through.objects.filter(pk=link.pk).exists())
        self.assert_unclaimed(source, project, object_ids)
        link.delete()

        outside = create.create_object("typeclasses.rooms.Room", key="Outside", nohome=True)
        exit_obj = create.create_object(
            "typeclasses.exits.Exit", key="elsewhere", location=self.plaza, destination=outside
        )
        exit_obj.aliases.add("external-route")
        alias = exit_obj.aliases.get("external-route", return_tagobj=True)
        self.assertEqual(exit_obj.aliases.all(), ["external-route"])
        Tag.objects.filter(pk=alias.pk).update(db_key="n")
        object_ids = set(ObjectDB.objects.values_list("id", flat=True))
        with self.assertRaisesRegex(ReplacementError, "direction is occupied"):
            self.execute(project)
        self.assertEqual(Tag.objects.filter(pk=alias.pk).values_list("db_key", flat=True).get(), "n")
        self.assert_unclaimed(source, project, object_ids)

    def test_failure_at_each_phase_restores_fresh_and_cached_state_and_retry(self):
        from web.builder import live_replacement

        source = self.source()
        project = self.candidate(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        room.db.played_state = {"visits": 42}
        original_ids = set(ObjectDB.objects.values_list("id", flat=True))
        original_scripts = set(ScriptDB.objects.values_list("id", flat=True))
        old_timers = [ScriptDB.objects.get(pk=entry["script_id"]) for entry in source.live_manifest["scripts"].values()]
        for phase in ("after_additions", "after_apply", "after_retire", "after_timers", "before_commit"):

            def fail(value, phase=phase):
                if value == phase:
                    raise RuntimeError("injected " + phase)

            with (
                mock.patch.object(live_replacement, "_checkpoint", side_effect=fail),
                self.assertRaises(live_replacement.ReplacementError),
            ):
                self.execute(project)
            self.assertEqual(room.key, "Room 1", phase)
            self.assertEqual(dict(room.db.played_state), {"visits": 42}, phase)
            fresh = ObjectDB.objects.get(pk=room.pk)
            fresh.attributes.reset_cache()
            self.assertEqual(fresh.key, "Room 1", phase)
            self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), original_ids, phase)
            self.assertEqual(set(ScriptDB.objects.values_list("id", flat=True)), original_scripts, phase)
            self.assertTrue(all(_timer_running(timer) for timer in old_timers), phase)
            project.refresh_from_db()
            source.refresh_from_db()
            self.assertEqual(project.status, "approved", phase)
            self.assertEqual(source.current_live_revision_id, source.pk, phase)
            self.assertEqual(project.replacement_journal["state"], "rolled_back", phase)
        self.execute(project)
        project.refresh_from_db()
        self.assertEqual(project.status, "live")

    def test_compensation_failure_is_visible_and_blocks_automatic_retry(self):
        from web.builder import live_replacement

        source = self.source()
        project = self.candidate(source)
        with (
            mock.patch.object(live_replacement, "_checkpoint", side_effect=RuntimeError("apply failure")),
            mock.patch.object(live_replacement, "_restore_object", side_effect=RuntimeError("restore failure")),
            self.assertRaisesRegex(live_replacement.ReplacementError, "compensation failed"),
        ):
            self.execute(project)
        project.refresh_from_db()
        self.assertEqual(project.status, "replacement_failed")
        self.assertTrue(project.replacement_journal["compensation_errors"])
        with self.assertRaises(live_replacement.ReplacementError):
            self.execute(project)

    def test_replacement_sandbox_must_be_cleaned_up_and_cannot_publish_as_copy(self):
        from web.builder.live_replacement import ReplacementError
        from web.builder.sandbox_cleanup import cleanup_unit

        source = self.source()
        project = self.candidate(source)
        sandbox_builder.build_unit(project.pk)
        with self.assertRaises(promotion.PromotionError):
            promotion.promote_unit(project.pk)
        with self.assertRaises(ReplacementError):
            self.execute(project)
        cleanup_unit(project.pk)
        project.refresh_from_db()
        self.execute(project)

    def test_api_requires_owner_and_reviewed_client_version(self):
        source = self.source()
        response = self.post_json(
            self.client_for(self.owner),
            reverse("builder:fork_revision", args=[source.pk]),
            {"version": source.version, "intent": "replacement"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        project = BuildProject.objects.get(pk=response.json()["id"])
        project.submit()
        project.approve(self.builder2, project.version)
        url = reverse("builder:replace_live", args=[project.pk])
        self.assertEqual(
            self.post_json(self.client_for(self.builder2), url, {"version": project.version}).status_code, 403
        )
        self.assertEqual(
            self.post_json(self.client_for(self.owner), url, {"version": project.version + 1}).status_code, 409
        )
        response = self.post_json(self.client_for(self.owner), url, {"version": project.version})
        self.assertEqual(response.status_code, 200, response.content)

    def test_lost_final_publication_update_restores_world_and_lineage_after_partial_record_writes(self):
        from django.db.models.query import QuerySet

        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        before = set(ObjectDB.objects.values_list("id", flat=True))
        real_update = QuerySet.update

        def lose_candidate_update(queryset, **fields):
            if queryset.model is BuildProject and fields.get("status") == "live":
                # Prove the failure occurs after both earlier metadata writes.
                current = BuildProject.objects.get(pk=source.pk)
                self.assertEqual(current.status, "superseded")
                self.assertEqual(current.current_live_revision_id, project.pk)
                return 0
            return real_update(queryset, **fields)

        with (
            mock.patch.object(QuerySet, "update", lose_candidate_update),
            self.assertRaises(ReplacementError),
        ):
            self.execute(project)
        source.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(source.status, "live")
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.assertIsNone(source.replacement_claim_id)
        self.assertEqual(project.status, "approved")
        self.assertEqual(project.replacement_journal["actor_id"], self.owner.pk)
        self.assertEqual(room.key, "Room 1")
        self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), before)
        self.execute(project)
        project.refresh_from_db()
        self.assertEqual(project.replacement_journal["actor_id"], self.owner.pk)
        self.assertIn("completed_at", project.replacement_journal)

    def test_failed_exit_compensation_cannot_cascade_delete_a_retained_live_exit(self):
        from web.builder import live_replacement
        from web.builder.revisions import fork_replacement

        source = self.source()
        project = fork_replacement(source.pk, self.owner, source.version)
        project.map_data["rooms"]["r4"] = {"name": "Staged room", "description": "Unpublished addition"}
        project.map_data["exits"]["e1a"]["target"] = "r4"
        project.save(update_fields=["map_data"])
        project.submit()
        project.approve(self.builder2, project.version)
        retained_exit_id = source.live_manifest["exits"]["e1a"]["object_id"]
        real_restore = live_replacement._restore_object

        def fail_after_apply(phase):
            if phase == "after_apply":
                raise RuntimeError("apply boundary")

        def fail_retained_exit(state):
            if state["object_id"] == retained_exit_id:
                raise RuntimeError("retained exit restore failed")
            return real_restore(state)

        with (
            mock.patch.object(live_replacement, "_checkpoint", side_effect=fail_after_apply),
            mock.patch.object(live_replacement, "_restore_object", side_effect=fail_retained_exit),
            self.assertRaisesRegex(live_replacement.ReplacementError, "compensation failed"),
        ):
            self.execute(project)
        self.assertTrue(ObjectDB.objects.filter(pk=retained_exit_id).exists())
        project.refresh_from_db()
        self.assertEqual(project.status, "replacement_failed")
        self.assertTrue(ObjectDB.objects.filter(pk__in=project.replacement_journal["created_object_ids"]).exists())

    def test_stored_lineage_drift_cannot_transfer_an_old_review_to_a_different_root(self):
        from web.builder.live_replacement import ReplacementError

        source = self.source()
        project = self.candidate(source)
        BuildProject.objects.filter(pk=project.pk).update(lineage_root=None)
        before = set(ObjectDB.objects.values_list("id", flat=True))
        with self.assertRaises(ReplacementError):
            self.execute(project)
        self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), before)
