"""
The builder review gate: who may use the builder, who may review, and what
is locked once a project is submitted.

These run against the real test DB with Django's test Client. Accounts get
in-game permission strings (Builder, Admin); Django's is_staff grants nothing.
"""

import importlib
import json
import re
from pathlib import Path
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.admin.sites import site as admin_site
from django.test import Client, RequestFactory, TestCase
from django.urls import URLPattern, reverse
from evennia.utils import create

from web.builder import urls as builder_urls
from web.builder.models import BuildProject, StaleReviewError
from web.builder.sandbox_bridge import create_sandbox_from_project
from web.builder.views import CleanupSandboxView, RoomTriggersAPI

REVIEW_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "builder" / "review.html"


def _map(room_name="Hall"):
    return {
        "schema_version": 1,
        "rooms": {
            "r1": {"name": room_name, "description": "A room.", "x": 0, "y": 0},
            "r2": {"name": "Annex", "description": "Another.", "x": 100, "y": 0},
        },
        "exits": {"e1": {"source": "r1", "target": "r2", "name": "east"}},
        "objects": {},
    }


class BuilderGateTestBase(TestCase):
    def setUp(self):
        self.owner = self._account("owner", ["Builder"])
        self.builder2 = self._account("builder2", ["Builder"])
        self.admin = self._account("admin", ["Admin"])
        self.staff_only = self._account("staffonly", None)
        self.staff_only.is_staff = True
        self.staff_only.save()
        self.room = create.create_object("typeclasses.rooms.Room", key="Plaza", nohome=True)

    def _account(self, name, perms):
        return create.create_account(name, f"{name}@example.com", "testpassword123", permissions=perms)

    def client_for(self, account):
        client = Client()
        client.force_login(account)
        return client

    def post_json(self, client, url, data=None):
        body = json.dumps(data) if data is not None else ""
        return client.post(url, data=body, content_type="application/json")

    def make_project(self, user, name="Area", map_data=None, **fields):
        return BuildProject.objects.create(user=user, name=name, map_data=map_data or _map(), **fields)

    def submit(self, client, project, room_id=None, direction="n"):
        payload = {"notes": "please review"}
        if room_id is not False:
            payload["connection_room_id"] = room_id or self.room.id
        if direction is not None:
            payload["connection_direction"] = direction
        return self.post_json(client, reverse("builder:submit_project", args=[project.pk]), payload)

    def approve(self, client, project, version="current"):
        payload = {}
        if version == "current":
            payload["version"] = BuildProject.objects.get(pk=project.pk).version
        elif version is not None:
            payload["version"] = version
        return self.post_json(client, reverse("builder:approve_project", args=[project.pk]), payload)

    def reject(self, client, project, notes="needs more description", version="current"):
        payload = {"notes": notes}
        if version == "current":
            payload["version"] = BuildProject.objects.get(pk=project.pk).version
        elif version is not None:
            payload["version"] = version
        return self.post_json(client, reverse("builder:reject_project", args=[project.pk]), payload)

    def submitted_project(self, user, **kwargs):
        project = self.make_project(user, **kwargs)
        resp = self.submit(self.client_for(user), project)
        self.assertEqual(resp.status_code, 200, resp.content)
        project.refresh_from_db()
        return project


class SelfApprovalTests(BuilderGateTestBase):
    def test_builder_cannot_approve_own_project(self):
        project = self.submitted_project(self.owner)
        owner_client = self.client_for(self.owner)

        self.assertEqual(self.approve(owner_client, project).status_code, 403)
        self.assertEqual(self.reject(owner_client, project).status_code, 403)

        project.refresh_from_db()
        self.assertEqual(project.status, "submitted")
        self.assertIsNone(project.reviewed_by)
        self.assertIsNone(project.approved_map_data)

    def test_second_builder_approves_and_is_recorded(self):
        project = self.submitted_project(self.owner)
        resp = self.approve(self.client_for(self.builder2), project)
        self.assertEqual(resp.status_code, 200, resp.content)

        project.refresh_from_db()
        self.assertEqual(project.status, "approved")
        self.assertEqual(project.reviewed_by, self.builder2)
        self.assertIsNotNone(project.reviewed_at)

    def test_model_refuses_builder_self_approval(self):
        project = self.submitted_project(self.owner)
        with self.assertRaises(PermissionError):
            project.approve(self.owner, project.version)

    def test_admin_may_self_approve_and_it_is_visible(self):
        project = self.submitted_project(self.admin, name="Admin Area")
        admin_client = self.client_for(self.admin)
        resp = self.approve(admin_client, project)
        self.assertEqual(resp.status_code, 200, resp.content)

        project.refresh_from_db()
        self.assertEqual(project.reviewed_by, self.admin)
        self.assertEqual(project.reviewed_by, project.user)

        # The review list shows who approved it, flagged as a self-approval.
        data = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        entry = next(r for r in data["reviewed"] if r["id"] == project.pk)
        self.assertEqual(entry["reviewed_by"], "admin")
        self.assertTrue(entry["self_reviewed"])
        # The review page renders that list.
        page = self.client_for(self.builder2).get(reverse("builder:build_review"))
        self.assertContains(page, 'id="reviewed-list"')
        self.assertContains(page, "r.reviewed_by")

    def test_admin_may_self_reject_and_it_is_labelled(self):
        project = self.submitted_project(self.admin, name="Admin Area")
        self.assertEqual(self.reject(self.client_for(self.admin), project).status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.status, "draft")
        self.assertEqual(project.reviewed_by, project.user)

        data = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        entry = next(r for r in data["reviewed"] if r["id"] == project.pk)
        self.assertEqual(entry["outcome"], "rejected")
        self.assertTrue(entry["self_reviewed"])
        template = REVIEW_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("(self-reviewed)", template)
        self.assertNotIn("(self-approved)", template)

    def test_superuser_may_self_approve(self):
        su = create.create_account("root", "root@example.com", "testpassword123", is_superuser=True)
        project = self.submitted_project(su)
        self.assertEqual(self.approve(self.client_for(su), project).status_code, 200)

    def test_review_list_hides_buttons_for_own_project(self):
        self.submitted_project(self.owner)
        data = self.client_for(self.owner).get(reverse("builder:review_projects")).json()
        self.assertFalse(data["projects"][0]["can_review"])
        data = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        self.assertTrue(data["projects"][0]["can_review"])


class ReviewConcurrencyTests(BuilderGateTestBase):
    def test_review_requires_version(self):
        project = self.submitted_project(self.owner)
        client = self.client_for(self.builder2)
        self.assertEqual(self.approve(client, project, version=None).status_code, 400)
        self.assertEqual(self.reject(client, project, version=None).status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.status, "submitted")

    def test_review_page_payload_carries_version(self):
        project = self.submitted_project(self.owner)
        data = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        self.assertEqual(data["projects"][0]["version"], project.version)
        template = REVIEW_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("JSON.stringify({ version: version })", template)
        self.assertIn("version: currentProjectVersion", template)

    def test_stale_approve_is_409_and_snapshots_nothing(self):
        project = self.submitted_project(self.owner)
        seen = project.version
        # Rejected, edited and resubmitted after the reviewer loaded the card.
        self.assertEqual(self.reject(self.client_for(self.admin), project).status_code, 200)
        project.refresh_from_db()
        save = self.post_json(
            self.client_for(self.owner),
            reverse("builder:save_project"),
            {"id": project.pk, "name": project.name, "map_data": _map("Unseen"), "version": project.version},
        )
        self.assertEqual(save.status_code, 200)
        self.assertEqual(self.submit(self.client_for(self.owner), project).status_code, 200)

        resp = self.approve(self.client_for(self.builder2), project, version=seen)
        self.assertEqual(resp.status_code, 409)
        project.refresh_from_db()
        self.assertEqual(project.status, "submitted")
        self.assertIsNone(project.approved_map_data)

    def test_approve_after_concurrent_reject_is_refused(self):
        project = self.submitted_project(self.owner)
        stale = BuildProject.objects.get(pk=project.pk)  # reviewer B's copy
        BuildProject.objects.get(pk=project.pk).reject(self.admin, "not yet", project.version)

        with self.assertRaises(StaleReviewError):
            # B's in-memory copy still says "submitted".
            stale.approve(self.builder2, project.version)
        project.refresh_from_db()
        self.assertEqual(project.status, "draft")
        self.assertEqual(project.reviewed_by, self.admin)
        self.assertIsNone(project.approved_map_data)


class AuthorityTests(BuilderGateTestBase):
    def _route_urls(self, project):
        """Every builder route, filled with this project's ids."""
        for pattern in builder_urls.urlpatterns:
            self.assertIsInstance(pattern, URLPattern)
            kwargs = {}
            for name, converter in pattern.pattern.converters.items():
                kwargs[name] = project.pk if converter.regex == "[0-9]+" else "r1"
            yield pattern.name, reverse(f"builder:{pattern.name}", kwargs=kwargs)

    def test_is_staff_without_builder_perm_is_forbidden_everywhere(self):
        project = self.submitted_project(self.owner)
        client = self.client_for(self.staff_only)
        for name, url in self._route_urls(project):
            for method in ("get", "post"):
                resp = getattr(client, method)(url)
                self.assertEqual(resp.status_code, 403, f"{method.upper()} {name}")
            self.assertEqual(client.delete(url).status_code, 403, f"DELETE {name}")
        project.refresh_from_db()
        self.assertEqual(project.status, "submitted")

    def test_anonymous_is_sent_to_login(self):
        resp = Client().get(reverse("builder:dashboard"))
        self.assertEqual(resp.status_code, 302)

    def test_builder_reaches_builder_pages(self):
        client = self.client_for(self.owner)
        for name in ("dashboard", "create_project", "build_review"):
            self.assertEqual(client.get(reverse(f"builder:{name}")).status_code, 200)

    def test_build_and_promote_are_owner_or_admin(self):
        project = self.submitted_project(self.owner)
        self.approve(self.client_for(self.builder2), project)

        build_url = reverse("builder:build_sandbox", args=[project.pk])
        promote_url = reverse("builder:promote_project", args=[project.pk])
        other = self.client_for(self.builder2)
        self.assertEqual(self.post_json(other, build_url).status_code, 403)
        self.assertEqual(self.post_json(other, promote_url, {}).status_code, 403)

        fake = (True, {"sandbox_room_id": 1, "room_count": 2, "exit_count": 1})
        with mock.patch("web.builder.views.create_sandbox_from_project", return_value=fake) as build:
            self.assertEqual(self.post_json(self.client_for(self.owner), build_url).status_code, 200)
            self.assertEqual(self.post_json(self.client_for(self.admin), build_url).status_code, 200)
        self.assertEqual(build.call_count, 2)

        # Promote: the Admin passes the permission check (and then fails on
        # status, since nothing was really built).
        resp = self.post_json(self.client_for(self.admin), promote_url, {})
        self.assertEqual(resp.status_code, 400)

    def test_cleanup_is_owner_or_admin(self):
        # The route is unrouted until PR 8, so call the view directly.
        project = self.make_project(self.owner, status="built", sandbox_room_id=1)
        factory = RequestFactory()

        def call(user):
            request = factory.post("/cleanup/")
            request.user = user
            return CleanupSandboxView.as_view()(request, pk=project.pk)

        result = (True, {"deleted_rooms": 0, "deleted_exits": 0, "deleted_objects": 0})
        with mock.patch("web.builder.sandbox_cleanup.cleanup_sandbox_for_project", return_value=result) as cleanup:
            self.assertEqual(call(self.builder2).status_code, 403)
            self.assertEqual(cleanup.call_count, 0)
            self.assertEqual(call(self.owner).status_code, 200)
            self.assertEqual(call(self.admin).status_code, 200)
        self.assertEqual(cleanup.call_count, 2)

    def test_owner_may_delete_only_drafts(self):
        client = self.client_for(self.owner)
        draft = self.make_project(self.owner)
        url = reverse("builder:delete_project", args=[draft.pk])
        self.assertEqual(self.client_for(self.builder2).post(url).status_code, 403)
        self.assertEqual(client.post(url).status_code, 200)
        self.assertFalse(BuildProject.objects.filter(pk=draft.pk).exists())

        project = self.submitted_project(self.owner)
        self.approve(self.client_for(self.builder2), project)
        url = reverse("builder:delete_project", args=[project.pk])
        self.assertEqual(client.post(url).status_code, 409)
        self.assertEqual(client.delete(url).status_code, 409)
        project.refresh_from_db()
        self.assertEqual(project.reviewed_by, self.builder2)
        self.assertIsNotNone(project.approved_map_data)

    def test_admin_may_delete_reviewed_project(self):
        project = self.submitted_project(self.owner)
        self.approve(self.client_for(self.builder2), project)
        url = reverse("builder:delete_project", args=[project.pk])
        self.assertEqual(self.client_for(self.admin).post(url).status_code, 200)
        self.assertFalse(BuildProject.objects.filter(pk=project.pk).exists())

    def test_django_admin_cannot_edit_review_record(self):
        model_admin = admin_site._registry[BuildProject]
        readonly = set(model_admin.get_readonly_fields(None))
        for field in ("user", "status", "reviewed_by", "reviewed_at", "approved_map_data"):
            self.assertIn(field, readonly)

    def test_connection_room_list_shows_live_rooms_only(self):
        sandbox = create.create_object("typeclasses.rooms.Room", key="Sandbox Hall", nohome=True)
        sandbox.tags.add("sandbox")
        sandbox.tags.add("project_99")
        client = self.client_for(self.owner)

        resp = client.get(reverse("builder:connection_rooms"))
        self.assertEqual(resp.status_code, 200)
        ids = [room["id"] for room in resp.json()["rooms"]]
        self.assertIn(self.room.id, ids)
        self.assertNotIn(sandbox.id, ids)

        # A room picked from that list is accepted on submit.
        project = self.make_project(self.owner)
        self.assertEqual(self.submit(client, project, room_id=ids[0]).status_code, 200)

    def test_private_project_hidden_from_other_builders(self):
        project = self.make_project(self.owner, is_public=False)
        other = self.client_for(self.builder2)
        self.assertEqual(
            other.get(reverse("builder:edit_project", args=[project.pk])).status_code,
            403,
        )
        self.assertEqual(
            other.get(reverse("builder:get_project", args=[project.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client_for(self.owner).get(reverse("builder:edit_project", args=[project.pk])).status_code,
            200,
        )


class ImmutabilityTests(BuilderGateTestBase):
    def save(self, client, project, map_data, version="current"):
        payload = {"id": project.pk, "name": project.name, "map_data": map_data}
        if version == "current":
            payload["version"] = project.version
        elif version is not None:
            payload["version"] = version
        return self.post_json(client, reverse("builder:save_project"), payload)

    def test_draft_save_bumps_version(self):
        project = self.make_project(self.owner)
        resp = self.save(self.client_for(self.owner), project, _map("Renamed"))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["version"], 2)
        project.refresh_from_db()
        self.assertEqual(project.map_data["rooms"]["r1"]["name"], "Renamed")

    def test_save_without_version_is_400(self):
        project = self.make_project(self.owner)
        resp = self.save(self.client_for(self.owner), project, _map("X"), version=None)
        self.assertEqual(resp.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.map_data["rooms"]["r1"]["name"], "Hall")

    def test_save_with_stale_version_is_409(self):
        project = self.make_project(self.owner)
        resp = self.save(self.client_for(self.owner), project, _map("X"), version=99)
        self.assertEqual(resp.status_code, 409)
        project.refresh_from_db()
        self.assertEqual(project.version, 1)

    def test_snapshot_taken_on_approval_and_save_after_approval_is_409(self):
        project = self.submitted_project(self.owner)
        self.approve(self.client_for(self.builder2), project)
        project.refresh_from_db()

        snapshot = project.approved_map_data
        self.assertEqual(snapshot["map_data"], project.map_data)
        self.assertEqual(snapshot["connection_room_id"], self.room.id)
        self.assertEqual(snapshot["connection_direction"], "n")

        owner = self.client_for(self.owner)
        resp = self.save(owner, project, _map("<swapped after review>"))
        self.assertEqual(resp.status_code, 409)

        trigger = {"id": "t1", "type": "entry", "action": "send_message", "parameters": {"message": "hi"}}
        url = reverse("builder:room_triggers", args=[project.pk, "r1"])
        self.assertEqual(self.post_json(owner, url, trigger).status_code, 409)
        delete_url = reverse("builder:room_trigger_detail", args=[project.pk, "r1", "t0"])
        self.assertEqual(owner.delete(delete_url).status_code, 409)

        project.refresh_from_db()
        self.assertEqual(project.approved_map_data, snapshot)
        self.assertEqual(project.map_data, snapshot["map_data"])

    def test_trigger_save_refuses_each_lock_on_its_own(self):
        project = self.make_project(self.owner)
        # Version moved on since this copy was read: refused, map unchanged.
        stale = BuildProject.objects.get(pk=project.pk)
        BuildProject.objects.filter(pk=project.pk).update(version=5)
        resp = RoomTriggersAPI._save_map(stale, _map("Stale"))
        self.assertEqual(resp.status_code, 409)
        # Status left draft since this copy was read: refused, map unchanged.
        current = BuildProject.objects.get(pk=project.pk)
        BuildProject.objects.filter(pk=project.pk).update(status="submitted")
        resp = RoomTriggersAPI._save_map(current, _map("Locked"))
        self.assertEqual(resp.status_code, 409)
        project.refresh_from_db()
        self.assertEqual(project.map_data["rooms"]["r1"]["name"], "Hall")
        # A current draft copy writes and bumps the version.
        BuildProject.objects.filter(pk=project.pk).update(status="draft")
        fresh = BuildProject.objects.get(pk=project.pk)
        self.assertIsNone(RoomTriggersAPI._save_map(fresh, _map("Saved")))
        project.refresh_from_db()
        self.assertEqual(project.version, 6)
        self.assertEqual(project.map_data["rooms"]["r1"]["name"], "Saved")

    def test_trigger_post_and_delete_on_submitted_project_are_409(self):
        trigger = {"id": "t0", "type": "entry", "action": "send_message", "parameters": {"message": "hi"}}
        data = _map()
        data["rooms"]["r1"]["triggers"] = [trigger]
        project = self.submitted_project(self.owner, map_data=data)
        owner = self.client_for(self.owner)
        url = reverse("builder:room_triggers", args=[project.pk, "r1"])
        self.assertEqual(self.post_json(owner, url, dict(trigger, id="t1")).status_code, 409)
        delete_url = reverse("builder:room_trigger_detail", args=[project.pk, "r1", "t0"])
        self.assertEqual(owner.delete(delete_url).status_code, 409)
        project.refresh_from_db()
        self.assertEqual(project.map_data, data)

    def test_save_while_submitted_is_409(self):
        project = self.submitted_project(self.owner)
        resp = self.save(self.client_for(self.owner), project, _map("Changed"))
        self.assertEqual(resp.status_code, 409)

    def test_sandbox_build_reads_snapshot_not_map_data(self):
        project = self.submitted_project(self.owner)
        self.approve(self.client_for(self.builder2), project)
        # Simulate the live map drifting after approval.
        BuildProject.objects.filter(pk=project.pk).update(map_data=_map("Swapped"))

        built = {"sandbox_room_id": 1, "room_count": 2, "exit_count": 1}
        with mock.patch("web.builder.sandbox_bridge.run_sync_in_main_thread", return_value=built) as run:
            ok, _ = create_sandbox_from_project(project.pk)
        self.assertTrue(ok)
        built_map = run.call_args.args[2]
        self.assertEqual(built_map["rooms"]["r1"]["name"], "Hall")

    def test_rejected_project_is_editable_again(self):
        project = self.submitted_project(self.owner)
        resp = self.reject(self.client_for(self.builder2), project)
        self.assertEqual(resp.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.reviewed_by, self.builder2)
        resp = self.save(self.client_for(self.owner), project, _map("Fixed"))
        self.assertEqual(resp.status_code, 200)


class ReviewInputTests(BuilderGateTestBase):
    def test_reject_with_non_object_or_non_string_notes_is_400(self):
        project = self.submitted_project(self.owner)
        client = self.client_for(self.builder2)
        url = reverse("builder:reject_project", args=[project.pk])
        self.assertEqual(self.post_json(client, url, ["notes"]).status_code, 400)
        self.assertEqual(self.post_json(client, url, {"notes": 5, "version": project.version}).status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.status, "submitted")


class MigrationTests(TestCase):
    def test_unsnapshotted_approvals_return_to_draft(self):
        owner = create.create_account("mig", "mig@example.com", "testpassword123", permissions=["Builder"])
        stuck = BuildProject.objects.create(user=owner, name="Old", map_data=_map(), status="approved")
        good = BuildProject.objects.create(
            user=owner, name="New", map_data=_map(), status="approved", approved_map_data={"map_data": _map()}
        )
        built = BuildProject.objects.create(user=owner, name="Built", map_data=_map(), status="built")

        migration = importlib.import_module("web.builder.migrations.0006_unsnapshotted_approvals_to_draft")
        migration.unsnapshotted_approvals_to_draft(django_apps, None)

        for project in (stuck, good, built):
            project.refresh_from_db()
        self.assertEqual(stuck.status, "draft")
        self.assertIn("resubmit", stuck.rejection_notes)
        self.assertEqual(good.status, "approved")
        self.assertEqual(built.status, "built")


class SubmitConnectionTests(BuilderGateTestBase):
    def test_submit_without_connection_room_is_400(self):
        project = self.make_project(self.owner)
        resp = self.submit(self.client_for(self.owner), project, room_id=False)
        self.assertEqual(resp.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.status, "draft")

    def test_submit_without_direction_is_400(self):
        project = self.make_project(self.owner)
        resp = self.submit(self.client_for(self.owner), project, direction=None)
        self.assertEqual(resp.status_code, 400)

    def test_submit_with_non_room_is_400(self):
        thing = create.create_object("typeclasses.objects.Object", key="Rock", nohome=True)
        project = self.make_project(self.owner)
        resp = self.submit(self.client_for(self.owner), project, room_id=thing.id)
        self.assertEqual(resp.status_code, 400)

    def test_submit_with_sandbox_room_is_400(self):
        sandbox = create.create_object("typeclasses.rooms.Room", key="Sandbox", nohome=True)
        sandbox.tags.add("sandbox")
        project = self.make_project(self.owner)
        resp = self.submit(self.client_for(self.owner), project, room_id=sandbox.id)
        self.assertEqual(resp.status_code, 400)

    def test_submit_records_connection_and_review_shows_it(self):
        project = self.submitted_project(self.owner)
        self.assertEqual(project.connection_room_id, self.room.id)
        self.assertEqual(project.connection_direction, "n")
        self.assertEqual(project.submission_notes, "please review")

        data = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        conn = data["projects"][0]["connection"]
        self.assertEqual(conn["room_id"], self.room.id)
        self.assertEqual(conn["room_name"], "Plaza")
        page = self.client_for(self.builder2).get(reverse("builder:build_review"))
        self.assertContains(page, "formatConnection(project.connection)")


class XSSTests(BuilderGateTestBase):
    def test_room_name_cannot_close_editor_script(self):
        payload = "</script><script>x</script>"
        project = self.make_project(self.owner, map_data=_map(payload))
        for account in (self.owner, self.builder2):
            resp = self.client_for(account).get(reverse("builder:edit_project", args=[project.pk]))
            self.assertEqual(resp.status_code, 200)
            body = resp.content.decode()
            self.assertNotIn(payload, body)
            self.assertNotIn("</script><script>x", body)
            self.assertIn('id="map-data"', body)

    def test_project_name_is_escaped_in_editor(self):
        # The project name is rendered server-side (title and name input).
        project = self.make_project(self.owner, name='x" onmouseover="y')
        resp = self.client_for(self.owner).get(reverse("builder:edit_project", args=[project.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('onmouseover="y"', body)
        self.assertIn("x&quot; onmouseover=&quot;y", body)

    def test_review_page_does_not_build_handlers_from_names(self):
        name = 'x" onmouseover="y'
        self.submitted_project(self.owner, name=name)
        client = self.client_for(self.builder2)

        page = client.get(reverse("builder:build_review")).content.decode()
        self.assertNotIn("onmouseover=", page)

        # Static checks: project data is rendered client-side, so the served
        # page holds the JS that builds the cards, not the payload. No inline
        # handler may interpolate a template literal, buttons are wired by
        # data-id, and escapeHtml must encode both quote characters.
        self.assertIsNone(re.search(r"""on\w+\s*=\s*["'][^"']*\$\{""", page))
        self.assertIn("data-id=", page)
        escape_fn = re.search(r"function escapeHtml\(text\) \{(.*?)\n\}", page, re.S)
        self.assertIsNotNone(escape_fn)
        self.assertIn("&quot;", escape_fn.group(1))
        self.assertIn("&#39;", escape_fn.group(1))

        # The name reaches the browser only as JSON data.
        data = client.get(reverse("builder:review_projects")).json()
        self.assertEqual(data["projects"][0]["name"], name)
