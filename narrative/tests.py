import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from twisted.internet.defer import fail, succeed

from .models import (
    MemoryFact,
    NarrativeConsent,
    NarrativePersona,
    StoryGenerationRequest,
    StorySession,
)
from .services import active_consent, authorized_memory_context, configured_provider, generate_story, set_consent


class NarrativeStoryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.account = user_model.objects.create_user(username="narrative-player", password="test")
        self.other_account = user_model.objects.create_user(username="other-player", password="test")
        self.character = ObjectDB.objects.create(
            db_key="NarrativePlayer", db_typeclass_path="typeclasses.characters.Character", db_account=self.account
        )
        self.other_character = ObjectDB.objects.create(
            db_key="OtherNarrativePlayer",
            db_typeclass_path="typeclasses.characters.Character",
            db_account=self.other_account,
        )
        self.npc = ObjectDB.objects.create(db_key="NarrativeNPC", db_typeclass_path="typeclasses.characters.Character")
        self.persona = NarrativePersona.objects.create(character=self.npc, profile="A reserved night-shift clerk.")
        self.session = StorySession.objects.create(
            character=self.character,
            persona=self.persona,
            location="street",
            deterministic_outcome={"hunting_success": True, "hunger_after": 2},
            resume_state={"phase": "approach"},
        )

    def test_consent_is_account_and_character_specific(self):
        NarrativeConsent.objects.create(account=self.other_account, character=self.character, opted_in=True)
        self.assertFalse(active_consent(self.session))
        with self.assertRaises(PermissionError):
            set_consent(self.other_account, self.character, True)
        self.assertFalse(active_consent(self.session))
        set_consent(self.account, self.character, True)
        self.assertTrue(active_consent(self.session))

    def test_opt_out_closes_active_story_and_expires_pending_player_text(self):
        consent = NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="Private action.")

        set_consent(self.account, self.character, False)

        consent.refresh_from_db()
        request.refresh_from_db()
        self.session.refresh_from_db()
        self.assertFalse(consent.opted_in)
        self.assertEqual(self.session.status, StorySession.Status.CLOSED)
        self.assertEqual(self.session.current_action, "")
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.action_text, "")

    @override_settings(
        NARRATIVE_AI={
            "endpoint": "http://provider.example/v1/chat/completions",
            "model": "test-model",
            "api_key": "test-secret",
        }
    )
    def test_remote_cleartext_provider_is_disabled(self):
        self.assertIsNone(configured_provider())

    def test_malformed_provider_url_is_disabled(self):
        with override_settings(
            NARRATIVE_AI={
                "endpoint": "https://provider.example:invalid/v1/chat/completions",
                "model": "test-model",
                "api_key": "test-secret",
            }
        ):
            self.assertIsNone(configured_provider())

    def test_loopback_http_and_remote_https_providers_are_allowed(self):
        for endpoint in (
            "http://localhost:1234/v1/chat/completions",
            "http://127.0.0.1:1234/v1/chat/completions",
            "http://[::1]:1234/v1/chat/completions",
            "https://provider.example/v1/chat/completions",
        ):
            with (
                self.subTest(endpoint=endpoint),
                override_settings(
                    NARRATIVE_AI={
                        "endpoint": endpoint,
                        "model": "test-model",
                        "api_key": "test-secret",
                    }
                ),
            ):
                self.assertIsNotNone(configured_provider())

    @override_settings(NARRATIVE_AI=None)
    def test_disabled_story_start_does_not_call_hunt_or_change_hunger(self):
        from commands.v5.hunt import CmdHunt
        from commands.v5.utils.blood_utils import get_hunger

        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        caller = self.character
        caller.msg = Mock()
        hunger_before = get_hunger(caller)
        command = type("CommandStub", (), {"caller": caller, "args": "start street"})()
        with patch("commands.v5.hunt.hunt") as hunt:
            CmdHunt._story_hunt(command)
        hunt.assert_not_called()
        self.assertEqual(get_hunger(caller), hunger_before)
        self.assertIn("not configured", str(caller.msg.call_args_list))

    @override_settings(
        NARRATIVE_AI={
            "endpoint": "http://localhost:1234/v1/chat/completions",
            "model": "test-model",
            "api_key": "test-secret",
        }
    )
    def test_synchronous_generation_error_clears_session_action(self):
        from commands.v5.hunt import CmdHunt

        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        caller = self.character
        caller.msg = Mock()
        command = type("CommandStub", (), {"caller": caller, "args": "x" * 2001})()
        CmdHunt._story_hunt(command)
        self.session.refresh_from_db()
        self.assertEqual(self.session.current_action, "")
        self.assertTrue(any("limited to" in str(call) for call in caller.msg.call_args_list))

    def test_opt_out_prevents_provider_call_and_persists_no_request(self):
        class SpyProvider:
            calls = 0

            def generate(self, _messages):
                self.calls += 1
                return succeed('{"prose":"ignored","citations":[]}')

        provider = SpyProvider()
        with self.assertRaises(PermissionError):
            generate_story(self.session, "Approach the stranger.", provider, scheduler=lambda function: function())
        self.assertEqual(provider.calls, 0)
        self.assertFalse(StoryGenerationRequest.objects.exists())

    @override_settings(NARRATIVE_AI=None)
    def test_disabled_provider_sends_nothing_and_preserves_rules_outcome(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        before = dict(self.session.deterministic_outcome)
        with self.assertRaisesRegex(RuntimeError, "no story request was sent"):
            generate_story(self.session, "Continue.", scheduler=lambda function: function())
        self.session.refresh_from_db()
        self.assertEqual(self.session.deterministic_outcome, before)
        self.assertFalse(StoryGenerationRequest.objects.exists())

    def test_memory_context_is_scoped_approved_and_unexpired(self):
        def fact(text, **kwargs):
            return MemoryFact.objects.create(
                persona=self.persona, text=text, staff_entry="Staff-curated note.", **kwargs
            )

        fact("Publicly known detail", visibility=MemoryFact.Visibility.PUBLIC, status=MemoryFact.Status.APPROVED)
        fact(
            "This player's secret",
            visibility=MemoryFact.Visibility.PRIVATE,
            subject=self.character,
            status=MemoryFact.Status.APPROVED,
        )
        fact(
            "Other player's secret",
            visibility=MemoryFact.Visibility.PRIVATE,
            subject=self.other_character,
            status=MemoryFact.Status.APPROVED,
        )
        fact("Staff-only note", visibility=MemoryFact.Visibility.STAFF, status=MemoryFact.Status.APPROVED)
        fact("Unreviewed suggestion", visibility=MemoryFact.Visibility.PUBLIC, status=MemoryFact.Status.DRAFT)
        fact(
            "Expired detail",
            visibility=MemoryFact.Visibility.PUBLIC,
            status=MemoryFact.Status.APPROVED,
            expires_at=timezone.now(),
        )

        memory = authorized_memory_context(self.session)
        texts = {item["text"] for item in memory}
        self.assertEqual(texts, {"Publicly known detail", "This player's secret"})
        self.assertNotIn("Other player's secret", " ".join(item["text"] for item in memory))

    def test_persisted_request_keeps_deterministic_outcome_and_expires_action(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class StubProvider:
            def generate(self, messages):
                self.messages = messages
                return succeed(json.dumps({"prose": "A shadow passes beneath the streetlamp.", "citations": []}))

        provider = StubProvider()
        deferred = generate_story(
            self.session, "I watch from the doorway.", provider, scheduler=lambda function: function()
        )
        response = []
        deferred.addCallback(response.append)
        self.assertEqual(response[0], "A shadow passes beneath the streetlamp.")
        self.session.refresh_from_db()
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.SUCCEEDED)
        self.assertEqual(request.response, response[0])
        self.assertEqual(request.action_text, "")
        self.assertEqual(self.session.deterministic_outcome, {"hunting_success": True, "hunger_after": 2})
        self.assertIn("I watch from the doorway.", provider.messages[-1]["content"])

    def test_provider_error_is_persisted_without_secret_text(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class BrokenProvider:
            def generate(self, _messages):
                return fail(RuntimeError("provider secret=do-not-store"))

        deferred = generate_story(self.session, "Look around.", BrokenProvider(), scheduler=lambda function: function())
        deferred.addErrback(lambda _failure: None)
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertNotIn("do-not-store", request.error)
        self.assertEqual(request.action_text, "")

    def test_session_completion_expires_raw_action_text(self):
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="private action")
        self.session.complete()
        request.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.action_text, "")
        self.assertEqual(self.session.current_action, "")
        self.assertEqual(self.session.status, StorySession.Status.COMPLETED)

    def test_untrusted_citation_rejects_provider_result(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class InvalidCitationProvider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "A voice calls.", "citations": ["not-authorized"]}))

        deferred = generate_story(
            self.session, "Listen.", InvalidCitationProvider(), scheduler=lambda function: function()
        )
        deferred.addErrback(lambda _failure: None)
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.response, "")
        self.assertEqual(request.action_text, "")

    def test_invalid_provider_json_is_persisted_as_failure(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class InvalidJSONProvider:
            def generate(self, _messages):
                return succeed("{not-json")

        deferred = generate_story(self.session, "Wait.", InvalidJSONProvider(), scheduler=lambda function: function())
        deferred.addErrback(lambda _failure: None)
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.response, "")
        self.assertEqual(request.action_text, "")

    def test_pending_request_recovers_and_persists_response(self):
        from .services import recover_pending_requests

        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="Resume me.")

        class RecoveryProvider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "The scene continues.", "citations": []}))

        self.assertEqual(recover_pending_requests(RecoveryProvider(), scheduler=lambda function: function()), 1)
        request.refresh_from_db()
        self.assertEqual(request.status, StoryGenerationRequest.Status.SUCCEEDED)
        self.assertEqual(request.response, "The scene continues.")


class NarrativeCommandDispatchTests(EvenniaCommandTest):
    def test_hunt_story_switch_runs_and_persists_a_normal_hunt(self):
        from commands.v5.hunt import CmdHunt

        class StubProvider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "A shadow moves.", "citations": []}))

        caller = self.char1
        caller.db.vampire = {"predator_type": "Alleycat", "hunger": 1}
        NarrativeConsent.objects.create(account=caller.account, character=caller, opted_in=True)
        hunt_result = {
            "success": True,
            "feeding": {"old_hunger": 1, "new_hunger": 2, "slaked": 1},
            "resonance": {"type": "sanguine"},
            "complication": None,
            "refused": None,
        }

        with (
            patch("narrative.services.configured_provider", return_value=StubProvider()),
            patch("narrative.services.reactor.callFromThread", side_effect=lambda callback: callback()),
            patch("commands.v5.hunt.hunt", return_value=hunt_result) as hunt,
        ):
            output = self.call(
                CmdHunt(),
                "/story start downtown",
                cmdstring="+hunt",
                caller=caller,
            )

        self.assertEqual(hunt.call_count, 1, output)
        session = StorySession.objects.get(character=caller, status=StorySession.Status.ACTIVE)
        request = StoryGenerationRequest.objects.get(session=session)
        self.assertEqual(session.deterministic_outcome["hunger_after"], 2)
        self.assertEqual(request.response, "A shadow moves.")
        self.assertIn("[AI-generated narrative]", output)
