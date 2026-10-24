"""Reviewed inert fixtures through the complete builder lifecycle."""

import copy
import json
import subprocess
from pathlib import Path
from unittest import mock

from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from evennia.objects.models import ObjectDB
from evennia.typeclasses.attributes import Attribute
from evennia.utils import create
from evennia.utils.dbserialize import from_pickle
from evennia.utils.idmapper.models import flush_cache

from web.builder import promotion, sandbox_builder, sandbox_cleanup
from web.builder.models import BuildProject
from web.builder.test_sandbox import SandboxTestBase, area_map
from web.builder.validators import validate_build_map


def fixture_map(count=1):
    data = area_map()
    data["objects"] = {
        f"f{i}": {"prototype_id": "wooden_chair", "prototype_revision": 1, "room_id": "r1", "name": f"Chair {i}"}
        for i in range(count)
    }
    return data


class PrototypeCatalogTests(SandboxTestBase):
    def test_catalog_requires_builder_and_returns_real_curated_entries(self):
        url = reverse("builder:prototypes")
        self.assertEqual(self.client.get(url).status_code, 302)
        player = create.create_account("catalog_player", "p@example.com", "testpassword123")
        self.assertEqual(self.client_for(player).get(url).status_code, 403)
        response = self.client_for(self.owner).get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data["catalog_version"], str)
        chair = next(p for p in data["prototypes"] if p["id"] == "wooden_chair")
        self.assertEqual(chair["revision"], 1)
        self.assertTrue(chair["label"] and chair["description"])
        self.assertNotIn("typeclass", chair)

    def test_unknown_ids_and_revisions_fail(self):
        for key, value in (
            ("prototype_id", "unknown"),
            ("prototype_revision", 999),
            ("prototype_revision", True),
            ("prototype_revision", "1"),
        ):
            data = fixture_map()
            data["objects"]["f0"][key] = value
            self.assertTrue(validate_build_map(data), (key, value))


class PrototypePlacementTests(SandboxTestBase):
    def test_only_bounded_placements_in_existing_rooms_are_accepted(self):
        self.assertEqual(validate_build_map(fixture_map()), [])
        for value in (None, [], {"bad id": fixture_map()["objects"]["f0"]}):
            data = fixture_map()
            data["objects"] = value
            self.assertTrue(validate_build_map(data))
        data = fixture_map()
        data["objects"]["f0"]["room_id"] = "missing"
        self.assertTrue(validate_build_map(data))

    def test_project_and_per_room_limits(self):
        from web.builder.prototype_catalog import MAX_FIXTURES, MAX_FIXTURES_PER_ROOM

        data = fixture_map(MAX_FIXTURES_PER_ROOM + 1)
        self.assertTrue(validate_build_map(data))
        data = fixture_map(MAX_FIXTURES + 1)
        self.assertTrue(validate_build_map(data))

    def test_overrides_reuse_name_description_and_markup_limits(self):
        for key, value in (
            ("name", "x" * 81),
            ("description", "x" * 10001),
            ("name", "|lcquit|ltclick|le"),
            ("description", []),
        ):
            data = fixture_map()
            data["objects"]["f0"][key] = value
            self.assertTrue(validate_build_map(data), (key, value))

    def test_caller_cannot_supply_definition_behavior_or_object_identity(self):
        for key in (
            "typeclass",
            "locks",
            "attributes",
            "prototype",
            "prototype_parent",
            "scripts",
            "account",
            "dbref",
            "object_id",
            "definition",
            "definition_hash",
            "exec",
            "code",
        ):
            data = fixture_map()
            data["objects"]["f0"][key] = "malicious"
            self.assertTrue(validate_build_map(data), key)


class PrototypeLifecycleTests(SandboxTestBase):
    def setUp(self):
        # Django rolls back rows and reuses PKs, but Evennia's idmapper keeps
        # identities. Isolate the first case from preceding test classes too,
        # before account/room creation and bulk-inserted fixture Attributes.
        flush_cache()
        # Cleanup still flushes only after this fixture's timers have stopped.
        self.addCleanup(flush_cache)
        super().setUp()

    def test_production_fixture_controls_cross_save_reload(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                "node",
                str(Path(__file__).parent / "fixtures" / "prototype_editor.cjs"),
                str(root / "web" / "templates" / "builder" / "editor.html"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        client = self.client_for(self.owner)
        response = self.post_json(
            client, reverse("builder:save_project"), {"name": "Fixture controls", "map_data": payload}
        )
        self.assertTrue(response.json()["validation"]["is_valid"], response.content)
        saved = client.get(reverse("builder:get_project", args=[response.json()["id"]])).json()["project"]
        self.assertEqual(saved["map_data"]["objects"], payload["objects"])
        self.assertEqual(saved["map_data"]["objects"]["f1"]["name"], "Edited chair")

    def reviewed(self, data=None):
        project = BuildProject.objects.create(
            user=self.owner,
            name="Furnished area",
            map_data=data or fixture_map(),
            connection_room_id=self.plaza.pk,
            connection_direction="n",
        )
        project.submit()
        project.approve(self.builder2, project.version)
        return project

    def built(self):
        project = self.reviewed()
        sandbox_builder.build_unit(project.pk)
        project.refresh_from_db()
        return project

    def fixture(self, project):
        record = project.fixture_manifest["placements"]["f0"]
        return ObjectDB.objects.get(pk=record["object_id"])

    def test_save_reload_and_staff_review_show_exact_placement_and_definition_hash(self):
        client = self.client_for(self.owner)
        data = fixture_map()
        data["objects"]["f0"]["description"] = "Weathered backrest."
        response = self.post_json(client, reverse("builder:save_project"), {"name": "Furniture", "map_data": data})
        self.assertTrue(response.json()["validation"]["is_valid"], response.content)
        pk = response.json()["id"]
        saved = client.get(reverse("builder:get_project", args=[pk])).json()["project"]
        self.assertEqual(saved["map_data"]["objects"], data["objects"])
        response = self.post_json(
            client,
            reverse("builder:submit_project", args=[pk]),
            {"connection_room_id": self.plaza.pk, "connection_direction": "n"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        projects = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()["projects"]
        item = next(p for p in projects if p["id"] == pk)
        self.assertEqual(item["fixtures"]["f0"]["placement"], data["objects"]["f0"])
        self.assertEqual(len(item["fixtures"]["f0"]["definition_hash"]), 64)
        self.assertContains(client.get(reverse("builder:edit_project", args=[pk])), 'id="fixture-catalog"')

    def test_reviewed_definition_is_frozen_at_submission_and_not_reresolved(self):
        from web.builder import prototype_catalog

        project = BuildProject.objects.create(
            user=self.owner,
            name="Freeze",
            map_data=fixture_map(),
            connection_room_id=self.plaza.pk,
            connection_direction="n",
        )
        project.submit()
        frozen = copy.deepcopy(project.submitted_prototypes)
        with mock.patch.dict(prototype_catalog.CATALOG, {}, clear=True):
            project.approve(self.builder2, project.version)
            sandbox_builder.build_unit(project.pk)
        project.refresh_from_db()
        self.assertEqual(project.approved_map_data["prototypes"], frozen)
        self.assertEqual(self.fixture(project).key, "Chair 0")

    def test_build_creates_inert_fixture_with_exact_reviewed_provenance(self):
        project = self.built()
        obj = self.fixture(project)
        record = project.fixture_manifest["placements"]["f0"]
        self.assertEqual(obj.db_typeclass_path, "typeclasses.objects.Object")
        self.assertEqual(obj.db_location_id, project.built_object_ids["rooms"]["r1"])
        self.assertFalse(obj.access(self.owner, "get", no_superuser_bypass=True))
        self.assertFalse(obj.access(self.owner, "puppet", no_superuser_bypass=True))
        expected = {
            "project_id": project.pk,
            "placement_id": "f0",
            "approved_version": project.version,
            "prototype_id": "wooden_chair",
            "prototype_revision": 1,
            "definition_hash": project.approved_map_data["prototypes"]["f0"]["definition_hash"],
        }
        # Scalar reads bypass Evennia's identity mapper: prove the durable row
        # as well as the object handler's view of that exact reviewed record.
        persisted = (
            obj.db_attributes.filter(
                db_key="builder_fixture",
                db_model="objectdb",
                db_category=None,
                db_attrtype=None,
            )
            .values_list("db_value", flat=True)
            .get()
        )
        self.assertEqual(from_pickle(persisted), expected)
        self.assertEqual(obj.db.builder_fixture, expected)
        self.assertEqual(record["definition_hash"], expected["definition_hash"])
        self.assertEqual(record["prototype_revision"], 1)
        self.assertEqual(project.built_object_ids["fixtures"]["f0"], obj.pk)

    def test_rollback_after_fixture_creation_and_after_metadata_failure(self):
        for phase in ("_bulk_tag_and_set", "_start_timed_triggers"):
            project = self.reviewed()
            before = set(ObjectDB.objects.values_list("id", flat=True))
            with (
                mock.patch.object(sandbox_builder, phase, side_effect=RuntimeError("fixture failure")),
                self.assertRaisesRegex(RuntimeError, "fixture failure"),
            ):
                sandbox_builder.build_unit(project.pk)
            self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), before)
            project.refresh_from_db()
            self.assertEqual(project.fixture_manifest, {})
            self.assertEqual(project.status, "approved")

    def test_mid_fixture_creation_failure_records_each_created_object_for_undo(self):
        project = self.reviewed(fixture_map(2))
        original = sandbox_builder._create_fixture
        before = set(ObjectDB.objects.values_list("id", flat=True))
        calls = 0

        def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("second fixture")
            return original(*args, **kwargs)

        with (
            mock.patch.object(sandbox_builder, "_create_fixture", side_effect=fail),
            self.assertRaisesRegex(RuntimeError, "second fixture"),
        ):
            sandbox_builder.build_unit(project.pk)
        self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), before)

    def test_cleanup_deletes_only_verified_fixtures_and_clears_manifest(self):
        project = self.built()
        obj = self.fixture(project)
        foreign = create.create_object(
            "typeclasses.objects.Object",
            key="Tagged foreign",
            location=self.plaza,
            tags=["sandbox", f"project_{project.pk}"],
        )
        result = sandbox_cleanup.cleanup_unit(project.pk)
        self.assertEqual(result["deleted_objects"], 1)
        self.assertFalse(ObjectDB.objects.filter(pk=obj.pk).exists())
        self.assertTrue(ObjectDB.objects.filter(pk=foreign.pk).exists())
        project.refresh_from_db()
        self.assertEqual(project.fixture_manifest, {})
        self.assertEqual(project.status, "approved")

    def test_moved_fixture_and_foreign_fixture_contents_refuse_cleanup_and_promotion(self):
        for alteration in ("move", "contents"):
            project = self.built()
            obj = self.fixture(project)
            if alteration == "move":
                obj.location = self.plaza
            else:
                create.create_object("typeclasses.objects.Object", key="Foreign contents", location=obj)
            before = set(ObjectDB.objects.values_list("id", flat=True))
            with self.assertRaises(sandbox_cleanup.CleanupError):
                sandbox_cleanup.cleanup_unit(project.pk)
            with self.assertRaises(promotion.PromotionError):
                promotion.promote_unit(project.pk)
            self.assertEqual(set(ObjectDB.objects.values_list("id", flat=True)), before)
            self.assertTrue(obj.tags.has("sandbox"))

    def test_substituted_character_or_type_is_never_cleanup_authority(self):
        project = self.built()
        obj = self.fixture(project)
        obj.db_typeclass_path = "typeclasses.characters.Character"
        obj.save(update_fields=["db_typeclass_path"])
        with self.assertRaises(sandbox_cleanup.CleanupError):
            sandbox_cleanup.cleanup_unit(project.pk)
        self.assertTrue(ObjectDB.objects.filter(pk=obj.pk).exists())

    def test_changed_provenance_or_missing_manifest_refuses_cleanup(self):
        for alteration in ("provenance", "manifest"):
            project = self.built()
            obj = self.fixture(project)
            if alteration == "provenance":
                obj.db.builder_fixture = {"project_id": project.pk}
            else:
                BuildProject.objects.filter(pk=project.pk).update(fixture_manifest={})
            with self.assertRaises(sandbox_cleanup.CleanupError):
                sandbox_cleanup.cleanup_unit(project.pk)
            self.assertTrue(ObjectDB.objects.filter(pk=obj.pk).exists())

    def test_promotion_preserves_fixtures_and_durable_live_identity_manifest(self):
        project = self.built()
        obj = self.fixture(project)
        room_id = obj.db_location_id
        promotion.promote_unit(project.pk)
        project.refresh_from_db()
        obj.refresh_from_db()
        self.assertEqual(obj.db_location_id, room_id)
        self.assertFalse(obj.tags.has("sandbox"))
        self.assertEqual(project.live_manifest["fixtures"]["f0"]["object_id"], obj.pk)
        self.assertEqual(len(project.live_manifest["connection_exits"]), 2)
        self.assertEqual(project.live_manifest["approved_version"], project.version)
        self.assertEqual(project.built_object_ids, {})
        self.assertEqual(project.fixture_manifest, {})

    def test_promotion_failure_restores_fixture_tags_and_retains_manifest(self):
        project = self.built()
        obj = self.fixture(project)
        before = copy.deepcopy(project.fixture_manifest)
        with (
            mock.patch.object(promotion, "_create_connection_exit", side_effect=RuntimeError("connect failure")),
            self.assertRaisesRegex(RuntimeError, "connect failure"),
        ):
            promotion.promote_unit(project.pk)
        project.refresh_from_db()
        self.assertTrue(obj.tags.has("sandbox"))
        self.assertTrue(obj.tags.has(f"project_{project.pk}"))
        self.assertEqual(project.fixture_manifest, before)
        self.assertEqual(project.live_manifest, {})

    def test_partial_cleanup_retains_remaining_identities_and_can_resume(self):
        project = self.built()
        original = sandbox_cleanup._delete_rows
        calls = 0

        def fail_after_fixtures(ids):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("after fixture deletion")
            return original(ids)

        with mock.patch.object(sandbox_cleanup, "_delete_rows", side_effect=fail_after_fixtures):
            result = sandbox_cleanup.cleanup_unit(project.pk)
        self.assertEqual(result["deleted_objects"], 1)
        self.assertTrue(result["errors"])
        project.refresh_from_db()
        self.assertEqual(project.fixture_manifest["placements"], {})
        self.assertTrue(project.built_object_ids["cleanup_started"])
        with self.assertRaises(promotion.PromotionError):
            promotion.promote_unit(project.pk)
        result = sandbox_cleanup.cleanup_unit(project.pk)
        self.assertEqual(result["errors"], [])
        project.refresh_from_db()
        self.assertEqual(project.status, "approved")

    def test_forged_frozen_definition_cannot_create_a_character_even_with_matching_hash(self):
        from web.builder.revisions import approved_snapshot_hash

        project = self.reviewed()
        definition = project.approved_map_data["prototypes"]["f0"]["definition"]
        definition["typeclass"] = "typeclasses.characters.Character"
        project.approved_map_data["prototypes"]["f0"]["definition_hash"] = approved_snapshot_hash(definition)
        project.save(update_fields=["approved_map_data"])
        before = ObjectDB.objects.count()
        with self.assertRaises(sandbox_builder.BuildError):
            sandbox_builder.build_unit(project.pk)
        self.assertEqual(ObjectDB.objects.count(), before)

    def test_object_delete_failure_restores_fresh_and_cached_fixture_provenance_for_retry(self):
        from django.db.models.query import QuerySet
        from evennia.typeclasses.attributes import Attribute

        project = self.built()
        obj = self.fixture(project)
        fixture_id = obj.pk
        provenance = copy.deepcopy(dict(obj.db.builder_fixture))
        cached_attribute = obj.attributes.get("builder_fixture", return_obj=True)
        attribute_id = cached_attribute.pk
        original_delete = QuerySet.delete

        def fail_at_object_delete(queryset):
            if queryset.model is ObjectDB:
                # This boundary must come after the Attribute delete, not
                # between the whole _delete_rows calls as the old test did.
                self.assertFalse(Attribute.objects.filter(pk=attribute_id).exists())
                raise RuntimeError("object persistence boundary")
            return original_delete(queryset)

        with mock.patch.object(QuerySet, "delete", fail_at_object_delete):
            result = sandbox_cleanup.cleanup_unit(project.pk)
        self.assertTrue(result["errors"])
        self.assertIn("object persistence boundary", result["errors"][0])
        self.assertTrue(ObjectDB.objects.filter(pk=fixture_id).exists())
        self.assertTrue(Attribute.objects.filter(pk=attribute_id).exists())
        self.assertEqual(cached_attribute.pk, attribute_id)
        self.assertEqual(dict(cached_attribute.value), provenance)
        self.assertEqual(dict(obj.db.builder_fixture), provenance)
        ObjectDB.flush_cached_instance(obj)
        fresh = ObjectDB.objects.get(pk=fixture_id)
        self.assertEqual(dict(fresh.db.builder_fixture), provenance)
        project.refresh_from_db()
        self.assertEqual(project.fixture_manifest["placements"]["f0"]["object_id"], fixture_id)
        result = sandbox_cleanup.cleanup_unit(project.pk)
        self.assertEqual(result["errors"], [])
        project.refresh_from_db()
        self.assertEqual(project.status, "approved")


class PrototypeCacheIsolationTests(TestCase):
    def test_first_lifecycle_fixture_after_rolled_back_attribute_identities(self):
        # Reproduce Django's cross-TestCase PK reuse without depending on the
        # entire suite's test order. Normal saves populate Evennia's idmapper;
        # rolling back rows does not evict those Python identities.
        with transaction.atomic():
            warmed = [
                Attribute.objects.create(
                    db_key=f"rollback_cache_{index}",
                    db_model="objectdb",
                    db_value=None,
                )
                for index in range(64)
            ]
            transaction.set_rollback(True)
        self.assertFalse(Attribute.objects.filter(pk__in=[row.pk for row in warmed]).exists())
        self.assertIs(Attribute.get_cached_instance(warmed[-1].pk), warmed[-1])
        lifecycle = PrototypeLifecycleTests("test_build_creates_inert_fixture_with_exact_reviewed_provenance")
        try:
            # Use the real class's first setup/target path, not another copy of
            # build logic. This outer TestCase owns the isolated DB rollback.
            lifecycle.setUp()
            lifecycle.test_build_creates_inert_fixture_with_exact_reviewed_provenance()
        finally:
            lifecycle.doCleanups()
