"""Immutable draft forks must never edit the reviewed source or game objects."""

import copy

from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone

from web.builder.models import BuildProject
from web.builder.tests import BuilderGateTestBase, _map


class ProjectRevisionTests(BuilderGateTestBase):
    def source(self, status="approved"):
        snapshot = {"map_data": _map("Reviewed hall"), "connection_room_id": self.room.pk, "connection_direction": "n"}
        return self.make_project(
            self.owner,
            status=status,
            approved_map_data=snapshot,
            map_data=_map("Unreviewed drift"),
            description="Design notes",
            is_public=False,
            reviewed_by=self.builder2,
            reviewed_at=timezone.now(),
            rejection_count=2,
            rejection_notes="Old rejection",
            submission_notes="Old submission",
            sandbox_room_id=self.room.pk if status == "built" else None,
            built_object_ids={"rooms": {"r1": self.room.pk}} if status == "built" else {},
            promoted_at=timezone.now() if status == "live" else None,
        )

    def fork(self, project, actor=None, **payload):
        return self.post_json(
            self.client_for(actor or self.owner),
            reverse("builder:fork_revision", args=[project.pk]),
            {"version": project.version, **payload},
        )

    def test_approved_built_and_live_fork_reviewed_design_only(self):
        for status in ("approved", "built", "live"):
            with self.subTest(status=status):
                source = self.source(status)
                before = copy.deepcopy(BuildProject.objects.values().get(pk=source.pk))
                response = self.fork(source)
                self.assertEqual(response.status_code, 201, response.content)
                draft = BuildProject.objects.get(pk=response.json()["id"])
                self.assertEqual(draft.map_data, source.approved_map_data["map_data"])
                self.assertEqual(draft.description, source.description)
                self.assertFalse(draft.is_public)
                self.assertEqual(draft.connection_room_id, self.room.pk)
                self.assertEqual(draft.connection_direction, "n")
                self.assertEqual(draft.status, "draft")
                self.assertEqual(draft.version, 1)
                self.assertEqual(draft.revision_of_id, source.pk)
                self.assertEqual(draft.root_project_id, draft.pk)
                self.assertEqual(draft.revision_intent, "copy")
                self.assertIsNone(draft.approved_map_data)
                self.assertIsNone(draft.reviewed_by)
                self.assertIsNone(draft.reviewed_at)
                self.assertIsNone(draft.sandbox_room_id)
                self.assertIsNone(draft.promoted_at)
                self.assertEqual(draft.built_object_ids, {})
                self.assertEqual(draft.live_manifest, {})
                self.assertEqual(draft.rejection_count, 0)
                self.assertEqual(draft.rejection_notes, "")
                self.assertEqual(draft.submission_notes, "")
                self.assertEqual(BuildProject.objects.values().get(pk=source.pk), before)
                self.room.refresh_from_db()
                self.assertEqual(self.room.key, "Plaza")

    def test_nonowner_including_admin_cannot_fork(self):
        source = self.source()
        for actor in (self.builder2, self.admin):
            self.assertEqual(self.fork(source, actor).status_code, 403)
        self.assertEqual(BuildProject.objects.count(), 1)

    def test_stale_fork_and_noninteger_versions_fail(self):
        source = self.source()
        self.assertEqual(self.fork(source, version=source.version + 1).status_code, 409)
        for version in (None, True, "1"):
            self.assertEqual(self.fork(source, version=version).status_code, 400)
        self.assertEqual(BuildProject.objects.count(), 1)

    def test_draft_submitted_and_unsnapshotted_sources_fail(self):
        for status in ("draft", "submitted"):
            self.assertEqual(self.fork(self.source(status)).status_code, 409)
        source = self.source("live")
        BuildProject.objects.filter(pk=source.pk).update(approved_map_data=None)
        self.assertEqual(self.fork(source).status_code, 409)

    def test_source_lineage_survives_multiple_reviewed_generations(self):
        source = self.source()
        draft = BuildProject.objects.get(pk=self.fork(source).json()["id"])
        self.submit(self.client_for(self.owner), draft)
        draft.refresh_from_db()
        draft.approve(self.builder2, draft.version)
        descendant = BuildProject.objects.get(pk=self.fork(draft).json()["id"])
        self.assertEqual(descendant.revision_of_id, draft.pk)
        self.assertEqual(descendant.root_project_id, descendant.pk)
        with self.assertRaises(ProtectedError):
            source.delete()
        response = self.post_json(self.client_for(self.admin), reverse("builder:delete_project", args=[source.pk]), {})
        self.assertEqual(response.status_code, 409)

    def test_lineage_is_not_editable_after_creation(self):
        source = self.source()
        draft = BuildProject.objects.get(pk=self.fork(source).json()["id"])
        draft.revision_of = None
        with self.assertRaises(ValidationError):
            draft.save()

    def test_replacement_intent_is_not_silently_treated_as_copy(self):
        source = self.source("live")
        response = self.fork(source, intent="replacement")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(BuildProject.objects.count(), 1)

    def test_approval_of_new_revision_does_not_change_live_source(self):
        source = self.source("live")
        before = copy.deepcopy(BuildProject.objects.values().get(pk=source.pk))
        draft = BuildProject.objects.get(pk=self.fork(source).json()["id"])
        draft.map_data["rooms"]["r1"]["name"] = "Revision hall"
        draft.save(update_fields=["map_data"])
        response = self.submit(self.client_for(self.owner), draft, direction="s")
        self.assertEqual(response.status_code, 200, response.content)
        draft.refresh_from_db()
        draft.approve(self.builder2, draft.version)
        self.assertEqual(draft.approved_map_data["map_data"]["rooms"]["r1"]["name"], "Revision hall")
        self.assertEqual(draft.approved_map_data["revision"]["revision_of_id"], source.pk)
        self.assertEqual(draft.approved_map_data["revision"]["intent"], "copy")
        self.assertEqual(BuildProject.objects.values().get(pk=source.pk), before)

    def test_manifest_is_empty_for_historical_live_projects_and_not_copied(self):
        source = self.source("live")
        self.assertEqual(source.live_manifest, {})
        source.live_manifest = {"schema_version": 1, "project_id": source.pk, "rooms": {}}
        source.save(update_fields=["live_manifest"])
        draft = BuildProject.objects.get(pk=self.fork(source).json()["id"])
        self.assertEqual(draft.live_manifest, {})

    def test_fork_requires_authenticated_builder_and_object_body(self):
        source = self.source()
        url = reverse("builder:fork_revision", args=[source.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.post_json(self.client_for(self.staff_only), url, {"version": 1}).status_code, 403)
        self.assertEqual(self.post_json(self.client_for(self.owner), url, []).status_code, 400)

    def test_dashboard_editor_and_review_expose_lineage_and_copy_intent(self):
        source = self.source()
        client = self.client_for(self.owner)
        self.assertContains(client.get(reverse("builder:dashboard")), "Create draft copy")
        self.assertContains(client.get(reverse("builder:edit_project", args=[source.pk])), "Create draft copy")
        draft = BuildProject.objects.get(pk=self.fork(source).json()["id"])
        response = client.get(reverse("builder:get_project", args=[draft.pk]))
        self.assertEqual(response.json()["project"]["revision_of_id"], source.pk)
        self.assertEqual(response.json()["project"]["root_project_id"], draft.pk)
        self.submit(client, draft)
        data = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        item = next(item for item in data["projects"] if item["id"] == draft.pk)
        self.assertEqual(item["revision_intent"], "copy")
        self.assertEqual(item["revision_of_id"], source.pk)
