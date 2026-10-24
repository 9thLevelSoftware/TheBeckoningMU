"""Offline transport boundaries; no real HTTP requests or provider credentials."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from evennia.objects.models import ObjectDB
from twisted.internet.defer import Deferred
from twisted.internet.task import Clock
from twisted.python.failure import Failure
from twisted.web.client import ResponseDone
from twisted.web.http import PotentialDataLoss
from twisted.web.http_headers import Headers
from twisted.web.iweb import UNKNOWN_LENGTH

from traits.models import CharacterBio

from .models import NarrativeConsent, StoryGenerationRequest, StorySession
from .services import TwistedChatProvider, configured_provider, generate_story

CONFIG = {
    "endpoint": "http://localhost:1234/v1/chat/completions",
    "model": "offline-test-model",
    "api_key": "fixture-secret-never-store",
    "request_timeout_seconds": 3,
    "connect_timeout_seconds": 2,
    "response_max_bytes": 512,
    "prose_max_chars": 12,
}


class FakeAgent:
    def __init__(self):
        self.cancelled = False
        self.requests = []
        self.pending = Deferred(self._cancel)

    def _cancel(self, _deferred):
        self.cancelled = True

    def request(self, method, uri, headers, producer):
        self.requests.append((method, uri, headers, producer))
        return self.pending


class AbortTransport:
    def __init__(self):
        self.aborted = False

    def abortConnection(self):  # noqa: N802
        self.aborted = True


class FakeResponse:
    def __init__(self, length=UNKNOWN_LENGTH, code=200, headers=None):
        self.code = code
        self.length = length
        self.headers = Headers(headers or {})
        self.transport = AbortTransport()
        self.protocol = None

    def deliverBody(self, protocol):  # noqa: N802
        self.protocol = protocol
        protocol.makeConnection(self.transport)

    def send(self, data):
        self.protocol.dataReceived(data)

    def finish(self):
        self.protocol.connectionLost(Failure(ResponseDone()))


def envelope(prose="Quiet night."):
    return json.dumps({"choices": [{"message": {"content": json.dumps({"prose": prose, "citations": []})}}]}).encode()


class ProviderResponseLimitTests(SimpleTestCase):
    def setUp(self):
        self.clock = Clock()
        self.agent = FakeAgent()

    def begin(self, **overrides):
        with patch("narrative.services.reactor", self.clock):
            self.provider = TwistedChatProvider({**CONFIG, **overrides}, agent=self.agent)
        self.successes, self.failures = [], []
        self.result = self.provider.generate([{"role": "user", "content": "private player prompt"}])
        self.result.addCallbacks(self.successes.append, self.failures.append)
        return self.result

    def assert_failure(self, category):
        self.assertTrue(self.result.called)
        self.assertEqual(self.successes, [])
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(getattr(self.failures[0].value, "category", None), category)
        self.assertNotIn("fixture-secret", str(self.failures[0].value))
        self.assertNotIn("private player prompt", str(self.failures[0].value))
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_invalid_limits_disable_provider_before_dispatch(self):
        for key, bad_values in (
            ("request_timeout_seconds", (0, -1, 301, True, float("inf"), float("nan"), "3")),
            ("connect_timeout_seconds", (0, 301, False)),
            ("response_max_bytes", (0, 8388609, 1.5, True)),
            ("prose_max_chars", (0, 100001, 1.5, True)),
        ):
            for value in bad_values:
                with self.subTest(key=key, value=value), override_settings(NARRATIVE_AI={**CONFIG, key: value}):
                    self.assertIsNone(configured_provider())

    def test_headers_deadline_cancels_pending_request_and_settles_once(self):
        agent = self.agent

        class LateHeaders(Deferred):
            def cancel(self):
                # A connector may finish just as cancellation is issued.
                agent.cancelled = True

        self.agent.pending = LateHeaders()
        self.begin()
        self.clock.advance(3)
        self.assert_failure("timeout")
        self.assertTrue(self.agent.cancelled)
        response = FakeResponse()
        self.agent.pending.callback(response)
        self.assertTrue(response.transport.aborted)
        self.clock.advance(30)
        self.assertEqual(len(self.failures), 1)

    def test_stalled_body_uses_original_deadline_and_aborts(self):
        self.begin()
        self.clock.advance(2)
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(b'{"choices":')
        self.clock.advance(1)
        self.assert_failure("timeout")
        self.assertTrue(response.transport.aborted)
        response.send(envelope())
        response.finish()
        self.assertEqual(len(self.failures), 1)

    def test_headers_deadline_cancels_called_deferred_waiting_on_inner_request(self):
        # Agent.request has already connected, but its Deferred is paused on
        # HTTP11ClientProtocol.request until response headers arrive.
        inner = Deferred(self.agent._cancel)
        self.agent.pending.addCallback(lambda _connected: inner)
        self.agent.pending.callback(None)
        self.assertTrue(self.agent.pending.called)
        self.begin()
        self.clock.advance(3)
        self.assert_failure("timeout")
        self.assertTrue(self.agent.cancelled)

    def test_declared_oversize_aborts_without_buffering_body(self):
        self.begin()
        response = FakeResponse(length=513)
        self.agent.pending.callback(response)
        self.assert_failure("response_too_large")
        self.assertTrue(response.transport.aborted)

    def test_content_length_header_is_bounded_even_with_unknown_length(self):
        self.begin()
        response = FakeResponse(headers={b"Content-Length": [b"513"]})
        self.agent.pending.callback(response)
        self.assert_failure("response_too_large")
        self.assertTrue(response.transport.aborted)

    def test_chunked_actual_bytes_are_bounded(self):
        self.begin()
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(b"x" * 300)
        response.send(b"x" * 213)
        self.assert_failure("response_too_large")
        self.assertTrue(response.transport.aborted)
        response.finish()
        self.assertEqual(len(self.failures), 1)

    def test_actual_bytes_override_understated_declared_length(self):
        self.begin()
        response = FakeResponse(length=1)
        self.agent.pending.callback(response)
        response.send(b"x" * 513)
        self.assert_failure("response_too_large")
        self.assertTrue(response.transport.aborted)

    def test_malformed_envelope_or_content_fails_safely(self):
        for body in (
            b"fixture-secret-never-store",
            b"\xff",
            b"{}",
            b'{"choices":[]}',
            b'{"choices":[{"message":{"content":17}}]}',
            b'{"choices":[{"message":{"content":"fixture-secret-never-store"}}]}',
            envelope(""),
        ):
            with self.subTest(body=body):
                self.agent = FakeAgent()
                self.begin()
                response = FakeResponse()
                self.agent.pending.callback(response)
                response.send(body)
                response.finish()
                self.assert_failure("malformed_response")

    def test_oversized_prose_is_rejected(self):
        self.begin()
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(envelope("x" * 13))
        response.finish()
        self.assert_failure("response_too_large")

    def test_cancellation_before_headers_settles_and_cancels_transport(self):
        self.begin().cancel()
        self.assert_failure("canceled")
        self.assertTrue(self.agent.cancelled)

    def test_cancellation_during_body_ignores_late_data_and_completion(self):
        self.begin()
        response = FakeResponse()
        self.agent.pending.callback(response)
        self.result.cancel()
        self.assert_failure("canceled")
        self.assertTrue(response.transport.aborted)
        response.send(envelope())
        response.finish()
        self.assertEqual(len(self.failures), 1)

    def test_complete_response_wins_and_cancels_deadline(self):
        self.begin()
        response = FakeResponse()
        self.agent.pending.callback(response)
        self.clock.advance(2.9)
        response.send(envelope())
        response.finish()
        self.clock.advance(0.1)
        self.assertEqual(json.loads(self.successes[0]), {"prose": "Quiet night.", "citations": []})
        self.assertEqual(self.failures, [])
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_deadline_wins_response_completion_race(self):
        self.begin()
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(envelope())
        self.clock.callLater(3, response.finish)
        self.clock.advance(3)
        self.assert_failure("timeout")
        self.assertTrue(response.transport.aborted)

    def test_parse_time_counts_against_total_deadline(self):
        self.begin()
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(envelope())
        original = self.provider._extract_content

        def slow_parse(body):
            self.clock.rightNow += 3
            return original(body)

        with patch.object(self.provider, "_extract_content", slow_parse):
            response.finish()
        self.assert_failure("timeout")

    def test_http_failure_aborts_and_never_exposes_response_body(self):
        self.begin()
        response = FakeResponse(code=503)
        self.agent.pending.callback(response)
        self.assert_failure("upstream_failure")
        self.assertTrue(response.transport.aborted)

    def test_transport_error_does_not_expose_secret(self):
        self.begin()
        self.agent.pending.errback(RuntimeError("fixture-secret-never-store private player prompt"))
        self.assert_failure("upstream_failure")

    def test_incomplete_response_does_not_accept_even_valid_json(self):
        self.begin()
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(envelope())
        response.protocol.connectionLost(Failure(PotentialDataLoss()))
        self.assert_failure("upstream_failure")

    def test_extremely_large_config_integer_is_disabled_safely(self):
        with override_settings(NARRATIVE_AI={**CONFIG, "request_timeout_seconds": 10**1000}):
            self.assertIsNone(configured_provider())

    def test_excessively_nested_json_has_fixed_malformed_category(self):
        self.begin(response_max_bytes=4096)
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(b"[" * 1200 + b"]" * 1200)
        response.finish()
        self.assert_failure("malformed_response")


class ProviderFailurePersistenceTests(TestCase):
    def setUp(self):
        account = get_user_model().objects.create_user(username="provider-limits-player")
        character = ObjectDB.objects.create(
            db_key="ProviderLimitsPlayer", db_typeclass_path="typeclasses.characters.Character", db_account=account
        )
        CharacterBio.objects.create(character=character, account=account)
        NarrativeConsent.objects.create(account=account, character=character, opted_in=True)
        self.session = StorySession.objects.create(
            character=character,
            location="street",
            current_action="private player prompt",
            deterministic_outcome={"hunger_after": 2, "success": True},
        )
        self.clock, self.agent = Clock(), FakeAgent()
        self.provider = TwistedChatProvider(CONFIG, agent=self.agent, clock=self.clock)
        self.failures = []

    def start(self):
        result = generate_story(
            self.session, "private player prompt", self.provider, scheduler=lambda callback: callback()
        )
        result.addErrback(self.failures.append)
        return result

    def assert_terminal(self, result, category):
        self.assertTrue(result.called)
        self.assertEqual(len(self.failures), 1)
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.session.refresh_from_db()
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.error, category)
        self.assertEqual(request.action_text, "")
        self.assertEqual(request.response, "")
        self.assertEqual(self.session.current_action, "")
        self.assertEqual(self.session.deterministic_outcome, {"hunger_after": 2, "success": True})

    def test_missing_headers_deadline_persists_terminal_failure(self):
        result = self.start()
        self.clock.advance(3)
        self.assert_terminal(result, "timeout")

    def test_stalled_body_deadline_persists_terminal_failure(self):
        result = self.start()
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(b"fixture-secret-never-store private player prompt")
        self.clock.advance(3)
        self.assert_terminal(result, "timeout")
        self.assertTrue(response.transport.aborted)

    def test_malformed_body_persists_only_fixed_category(self):
        result = self.start()
        response = FakeResponse()
        self.agent.pending.callback(response)
        response.send(b"fixture-secret-never-store private player prompt")
        response.finish()
        self.assert_terminal(result, "malformed_response")
