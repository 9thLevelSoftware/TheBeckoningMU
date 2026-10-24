"""Permission composition across the real Chronicle HTML and session REST routes."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from evennia.objects.models import ObjectDB

from narrative.models import MemoryFact, NarrativePersona
from traits.models import CharacterBio

from .models import ChronicleEvent, ChronicleGenerationRequest


@override_settings(NARRATIVE_AI={})
class ChroniclePermissionMatrixTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="matrix-owner", password=None)
        self.other = users.create_user(username="matrix-other", password=None)
        self.staff = users.create_user(username="matrix-staff", password=None, is_staff=True)
        self.staff.permissions.add("Builder")
        self.flag_only = users.create_user(username="matrix-django-staff", password=None, is_staff=True)
        self.superuser = users.create_user(username="matrix-superuser", password=None, is_staff=True, is_superuser=True)
        self.characters = {
            user.pk: ObjectDB.objects.create(
                db_key=f"Matrix character {user.username}",
                db_typeclass_path="typeclasses.characters.Character",
            )
            for user in (self.owner, self.other, self.staff)
        }
        for user in (self.owner, self.other, self.staff):
            CharacterBio.objects.create(character=self.characters[user.pk], account=user, status="approved")
        self.events = {}
        self._event("public", visibility="public", status="published")
        for status in ("draft", "redacted", "superseded"):
            self._event(f"public-{status}", visibility="public", status=status)
            self._event(f"participant-{status}", visibility="participants", status=status, users=(self.owner,))
        for role in ("owner", "other", "staff"):
            self._event(role, visibility="participants", status="published", users=(getattr(self, role),))
        self._event("shared", visibility="participants", status="published", users=(self.owner, self.other))
        self._event("staff-only", visibility="staff", status="published", users=(self.owner,))
        npc = ObjectDB.objects.create(db_key="Matrix NPC", db_typeclass_path="typeclasses.characters.Character")
        persona = NarrativePersona.objects.create(character=npc)
        self.memory = MemoryFact.objects.create(
            persona=persona,
            subject=self.characters[self.owner.pk],
            text="MATRIX_PRIVATE_MEMORY_TEXT",
            staff_entry="MATRIX_PRIVATE_MEMORY_PROVENANCE",
            visibility="private",
        )

    def _event(self, name, *, users=(), **fields):
        event = ChronicleEvent.objects.create(
            idempotency_key=f"matrix-{name}",
            source_app="staff",
            source_type="scene",
            source_id=name,
            kind="scene.curated",
            title=f"MATRIX_TITLE_{name}",
            summary=f"MATRIX_SUMMARY_{name}",
            payload={"location": f"MATRIX_PAYLOAD_{name}"},
            **fields,
        )
        event.participants.add(*(self.characters[user.pk] for user in users))
        self.events[name] = event
        return event

    def _api_urls(self, character=None):
        character = character or self.characters[self.owner.pk]
        return (
            reverse("player_public_chronicle"),
            reverse("player_my_chronicle"),
            reverse("player_character_summary", args=(character.pk,)),
            reverse("player_character_chronicle", args=(character.pk,)),
        )

    def test_story_navigation_uses_builder_permission_without_django_staff_flag(self):
        self.staff.is_staff = False
        self.staff.save(update_fields=["is_staff"])
        for user, visible in ((self.staff, True), (self.flag_only, False)):
            self.client.force_login(user)
            for name in ("chronicle_public", "chronicle_mine"):
                with self.subTest(user=user.username, route=name):
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(b"Story Operations" in response.content, visible)

    def _mutations(self):
        return (
            (reverse("narrative_ops"), {"title": "New curated scene", "summary": "Staff summary"}),
            (
                reverse("narrative_ops_action", args=(self.events["public-draft"].pk, "publish")),
                {},
            ),
            (
                reverse("narrative_ops_action", args=(self.events["public"].pk, "correct")),
                {"title": "Corrected public scene", "summary": "Corrected summary", "payload": "{}"},
            ),
            (reverse("narrative_ops_action", args=(self.events["public"].pk, "redact")), {}),
            (
                reverse("narrative_ops_memory_action", args=(self.memory.pk, "approve")),
                {"expected_version": self.memory.version},
            ),
            (
                reverse("narrative_ops_memory_action", args=(self.memory.pk, "redact")),
                {"expected_version": self.memory.version},
            ),
            (
                reverse("narrative_ops_generate"),
                {"source_ids": [str(self.events["public"].pk)], "mode": "recap"},
            ),
        )

    def _snapshot(self):
        return (
            list(ChronicleEvent.objects.order_by("pk").values("id", "status", "title", "summary", "payload")),
            list(MemoryFact.objects.order_by("pk").values("id", "status", "text", "staff_entry")),
            list(ChronicleGenerationRequest.objects.order_by("pk").values()),
        )

    def _assert_event_projection(self, response, expected_names, *, json_response=False):
        self.assertEqual(response.status_code, 200)
        expected_ids = {self.events[name].pk for name in expected_names}
        if json_response:
            self.assertEqual({event["id"] for event in response.json()["events"]}, expected_ids)
        else:
            self.assertEqual({event.pk for event in response.context["events"]}, expected_ids)
        body = response.content.decode()
        for name, event in self.events.items():
            if name not in expected_names:
                for sentinel in (event.title, event.summary, event.payload["location"]):
                    self.assertNotIn(sentinel, body)
        self.assertNotIn(self.memory.text, body)
        self.assertNotIn(self.memory.staff_entry, body)

    def test_public_and_personal_pages_scope_all_publication_states_and_roles(self):
        for user in (None, self.owner, self.other, self.staff, self.superuser):
            with self.subTest(user=user):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                self._assert_event_projection(self.client.get(reverse("chronicle_public")), {"public"})
                personal = self.client.get(reverse("chronicle_mine"))
                if user is None:
                    self.assertEqual(personal.status_code, 302)
                    self.assertIn("next=", personal["Location"])
                    continue
                expected = {"public"}
                if user == self.owner:
                    expected |= {"owner", "shared"}
                elif user == self.other:
                    expected |= {"other", "shared"}
                elif user == self.staff:
                    expected |= {"staff"}
                self._assert_event_projection(personal, expected)

    def test_rest_public_and_personal_projections_do_not_leak_staff_or_foreign_content(self):
        for user, own_names in (
            (self.owner, {"owner", "shared"}),
            (self.other, {"other", "shared"}),
            (self.staff, {"staff"}),
            (self.superuser, set()),
        ):
            with self.subTest(user=user):
                self.client.force_login(user)
                self._assert_event_projection(
                    self.client.get(reverse("player_public_chronicle")), {"public"}, json_response=True
                )
                self._assert_event_projection(
                    self.client.get(reverse("player_my_chronicle")), {"public"} | own_names, json_response=True
                )
                if user.pk in self.characters:
                    self._assert_event_projection(
                        self.client.get(reverse("player_character_chronicle", args=(self.characters[user.pk].pk,))),
                        own_names,
                        json_response=True,
                    )

    def test_rest_authentication_and_safe_method_matrix(self):
        before = self._snapshot()
        for url in self._api_urls():
            for method in ("get", "head", "options", "post", "put", "patch", "delete", "trace"):
                with self.subTest(role="anonymous", url=url, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 401)
                    if method != "head":
                        self.assertEqual(response.json(), {"error": "authentication_required"})
        self.client.force_login(self.owner)
        for url in self._api_urls():
            for method in ("get", "head", "options"):
                with self.subTest(role="owner", url=url, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 200)
                    if method == "head":
                        self.assertEqual(response.content, b"")
                    if method == "options":
                        self.assertEqual(set(response["Allow"].split(", ")), {"GET", "HEAD", "OPTIONS"})
            for method in ("post", "put", "patch", "delete", "trace"):
                with self.subTest(role="owner", url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertEqual(self._snapshot(), before)

    def test_character_api_ownership_has_no_staff_or_superuser_bypass(self):
        for user in (self.owner, self.other, self.staff, self.superuser):
            self.client.force_login(user)
            for owner_id, character in self.characters.items():
                for route in ("player_character_summary", "player_character_chronicle"):
                    with self.subTest(user=user, character=character.pk, route=route):
                        response = self.client.get(reverse(route, args=(character.pk,)))
                        if owner_id == user.pk:
                            self.assertEqual(response.status_code, 200)
                            if route == "player_character_summary":
                                self.assertEqual(response.json()["character"]["id"], character.pk)
                        else:
                            self.assertEqual(response.status_code, 404)
                            self.assertEqual(response.json(), {"error": "character_not_found"})
                            self.assertNotIn(character.key, response.content.decode())

    def test_read_pages_allow_safe_methods_and_deny_writes(self):
        before = self._snapshot()
        for user, route in ((None, "chronicle_public"), (self.owner, "chronicle_mine")):
            self.client.logout()
            if user:
                self.client.force_login(user)
            url = reverse(route)
            for method in ("get", "head", "options"):
                with self.subTest(route=route, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 200)
                    if method == "head":
                        self.assertEqual(response.content, b"")
                    if method == "options":
                        self.assertEqual(set(response["Allow"].split(", ")), {"GET", "HEAD", "OPTIONS"})
            for method in ("post", "put", "patch", "delete", "trace"):
                with self.subTest(route=route, method=method):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertEqual(self._snapshot(), before)

    def test_staff_pages_and_mutations_require_staff_and_actions_do_not_mutate_on_safe_methods(self):
        before = self._snapshot()
        for user in (None, self.owner, self.other, self.flag_only):
            self.client.logout()
            if user:
                self.client.force_login(user)
            with self.subTest(user=user, route="staff-page"):
                self.assertEqual(self.client.get(reverse("narrative_ops")).status_code, 302)
            for url, data in self._mutations():
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self._snapshot(), before)
        for user in (self.staff, self.superuser):
            self.client.force_login(user)
            response = self.client.get(reverse("narrative_ops"))
            self.assertContains(response, self.events["staff-only"].summary)
            self.assertContains(response, self.memory.text)
            for url, _data in self._mutations()[1:]:
                for method in ("get", "head", "options", "put", "patch", "delete", "trace"):
                    with self.subTest(user=user, url=url, method=method):
                        response = getattr(self.client, method)(url)
                        if method == "head":
                            # Evennia enables Django's admindocs XViewMiddleware:
                            # staff HEAD requests return empty view metadata before
                            # dispatch, including for POST-only action views.
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.content, b"")
                            self.assertTrue(response.has_header("X-View"))
                        else:
                            self.assertEqual(response.status_code, 405)
        self.assertEqual(self._snapshot(), before)

    def test_every_staff_mutation_rejects_missing_or_invalid_csrf_without_side_effects(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        self.assertEqual(client.get(reverse("narrative_ops")).status_code, 200)
        self.assertIn(settings.CSRF_COOKIE_NAME, client.cookies)
        before = self._snapshot()
        for url, data in self._mutations():
            for token in (None, "invalid-csrf-token"):
                with self.subTest(url=url, token=token):
                    headers = {"HTTP_X_CSRFTOKEN": token} if token else {}
                    response = client.post(url, data, **headers)
                    self.assertEqual(response.status_code, 403)
        self.assertEqual(self._snapshot(), before)

    def test_valid_csrf_allows_staff_review_actions_and_keeps_generation_disabled(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        client.get(reverse("narrative_ops"))
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        for url, data in self._mutations():
            with self.subTest(url=url), self.captureOnCommitCallbacks(execute=True):
                if "/memories/" in url:
                    data = {**data, "expected_version": MemoryFact.objects.get(pk=self.memory.pk).version}
                self.assertEqual(client.post(url, data, HTTP_X_CSRFTOKEN=token).status_code, 302)
        self.events["public-draft"].refresh_from_db()
        self.assertEqual(self.events["public-draft"].status, "published")
        self.events["public"].refresh_from_db()
        self.assertEqual(self.events["public"].status, "redacted")
        self.assertTrue(ChronicleEvent.objects.filter(title="New curated scene", status="draft").exists())
        self.assertTrue(
            ChronicleEvent.objects.filter(supersedes=self.events["public"], title="", status="redacted").exists()
        )
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.status, "redacted")
        self.assertEqual(self.memory.text, "")
        self.assertIsNotNone(self.memory.approved_at)
        self.assertFalse(ChronicleGenerationRequest.objects.exists())


class WithdrawalProjectionTests(TestCase):
    def setUp(self):
        from .test_moderation import moderation_fixture

        self.staff, self.a = moderation_fixture("projection")
        self.owner = get_user_model().objects.create_user(username="projection-owner")
        self.other = get_user_model().objects.create_user(username="projection-other")
        self.character = ObjectDB.objects.create(
            db_key="Projection Player", db_typeclass_path="typeclasses.characters.Character"
        )
        CharacterBio.objects.create(character=self.character, account=self.owner)
        self.b = self.event("public-recap", self.a)
        self.c = self.event("participant-recap", self.b, visibility="participants")
        self.c.participants.add(self.character)

    def event(self, key, source=None, **changes):
        fields = {
            "source_app": "staff",
            "source_type": "scene",
            "source_id": key,
            "kind": "scene.curated",
            "title": key,
            "summary": "WITHDRAWAL-SENTINEL-" + key,
            "status": "published",
            "visibility": "public",
        }
        fields.update(changes)
        event = ChronicleEvent.objects.create(idempotency_key=key, **fields)
        if source:
            event.source_events.add(source)
        return event

    def test_html_and_rest_fresh_reads_hide_transitive_and_participant_prose_after_redaction(self):
        from .services import redact_event

        self.client.force_login(self.owner)
        urls = [
            reverse(name)
            for name in ("chronicle_public", "chronicle_mine", "player_public_chronicle", "player_my_chronicle")
        ]
        urls.append(reverse("player_character_chronicle", args=(self.character.pk,)))
        self.assertContains(self.client.get(reverse("chronicle_mine")), self.c.summary)
        redact_event(self.a.pk, self.staff)
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(self.b.summary, response.content.decode())
                self.assertNotIn(self.c.summary, response.content.decode())

    def test_warmed_serializer_reloads_sources_content_and_canonical_ownership(self):
        from .api import serialize_event

        warm = ChronicleEvent.objects.prefetch_related("source_events", "participants").get(pk=self.c.pk)
        self.assertIsNotNone(serialize_event(warm, "account", self.owner))
        CharacterBio.objects.filter(character=self.character).update(account=self.other)
        self.assertIsNone(serialize_event(warm, "account", self.owner))
        self.assertIsNotNone(serialize_event(warm, "account", self.other))
        ChronicleEvent.objects.filter(pk=self.a.pk).update(status="redacted")
        self.assertIsNone(serialize_event(warm, "account", self.other))

    def test_character_scope_cannot_borrow_another_owned_characters_private_sources(self):
        from .read_services import character_chronicle_for_account

        second = ObjectDB.objects.create(
            db_key="Second Projection Player", db_typeclass_path="typeclasses.characters.Character"
        )
        CharacterBio.objects.create(character=second, account=self.owner)
        source = self.event("other-character-source", visibility="participants")
        source.participants.add(second)
        self.c.source_events.add(source)
        self.assertNotIn(
            self.c.pk, [event.pk for event in character_chronicle_for_account(self.owner, self.character.pk)]
        )

    def test_metadata_drift_and_unknown_generated_provenance_never_receive_historical_rehash(self):
        import json

        from twisted.internet.defer import succeed

        from .generation import request_draft
        from .services import event_available, publish_event

        source_id = str(self.a.pk)

        class Provider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "Generated sentinel.", "citations": [source_id]}))

        with self.captureOnCommitCallbacks(execute=True):
            request = request_draft(
                self.staff, [source_id], "recap", provider=Provider(), scheduler=lambda callback: callback()
            )
        request.refresh_from_db()
        publish_event(request.draft_event_id, self.staff)
        saved = request.source_fingerprints
        self.assertTrue(event_available(request.draft_event_id, "public"))
        ChronicleEvent.objects.filter(pk=self.a.pk).update(title="Changed source metadata")
        self.assertFalse(event_available(request.draft_event_id, "public"))
        request.refresh_from_db()
        self.assertEqual(request.source_fingerprints, saved)
