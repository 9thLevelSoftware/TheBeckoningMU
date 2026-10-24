from __future__ import annotations

import json
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx
from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from oauth2_provider.models import AccessToken as OAuthAccessToken
from oauth2_provider.models import Application as OAuthApplication
from oauth2_provider.models import set_token_value

from traits.models import CharacterBio

from . import auth
from .app import RequestProtection, create_application
from .tools import _require_token, register_tools


class MCPWithdrawalTests(TestCase):
    def setUp(self):
        from evennia.objects.models import ObjectDB

        from chronicle.models import ChronicleEvent
        from chronicle.test_moderation import moderation_fixture

        self.staff, self.a = moderation_fixture("mcp-withdrawal")
        self.owner = get_user_model().objects.create_user(username="mcp-withdrawal-owner")
        self.other = get_user_model().objects.create_user(username="mcp-withdrawal-other")
        self.character = ObjectDB.objects.create(
            db_key="MCP Withdrawal", db_typeclass_path="typeclasses.characters.Character"
        )
        CharacterBio.objects.create(character=self.character, account=self.owner)
        self.b = ChronicleEvent.objects.create(
            idempotency_key="mcp-recap",
            source_app="staff",
            source_type="scene",
            source_id="mcp-recap",
            kind="scene.curated",
            status="published",
            visibility="public",
            title="MCP recap",
            summary="MCP-WITHDRAWAL-SENSITIVE",
        )
        self.b.source_events.add(self.a)
        self.c = ChronicleEvent.objects.create(
            idempotency_key="mcp-personal-recap",
            source_app="staff",
            source_type="scene",
            source_id="mcp-personal",
            kind="scene.curated",
            status="published",
            visibility="participants",
            title="MCP personal recap",
            summary="MCP-WITHDRAWAL-PERSONAL",
        )
        self.c.source_events.add(self.b)
        self.c.participants.add(self.character)

    def test_public_and_account_mcp_projections_recheck_transitive_source_withdrawal(self):
        from chronicle.services import redact_event

        from .tools import _account_chronicle_records, _chronicle_record, _public_chronicle_records

        warm = self.b
        self.assertIn(self.b.pk, {row["id"] for row in _public_chronicle_records(100)})
        self.assertIn(self.c.pk, {row["id"] for row in _account_chronicle_records(self.owner, 100)})
        redact_event(self.a.pk, self.staff)
        self.assertEqual(_public_chronicle_records(100), [])
        self.assertEqual(_account_chronicle_records(self.owner, 100), [])
        self.assertIsNone(_chronicle_record(warm))

    def test_warmed_account_record_rechecks_ownership_and_raw_ancestor_revocation(self):
        from chronicle.models import ChronicleEvent

        from .tools import _chronicle_record

        self.assertIsNotNone(_chronicle_record(self.c, "account", self.owner))
        CharacterBio.objects.filter(character=self.character).update(account=self.other)
        self.assertIsNone(_chronicle_record(self.c, "account", self.owner))
        self.assertIsNotNone(_chronicle_record(self.c, "account", self.other))
        ChronicleEvent.objects.filter(pk=self.a.pk).update(status="redacted")
        self.assertIsNone(_chronicle_record(self.c, "account", self.other))


def _valid_access_token(scopes):
    return AccessToken(
        token="",
        client_id="client",
        scopes=scopes,
        expires_at=int(time.time()) + 60,
        resource="https://mcp.example.test",
        subject="41",
        claims={"iss": "https://game.example.test/o"},
    )


class TokenVerifierTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(pk=41, is_active=True)
        self.application = SimpleNamespace(
            client_id="controlled-client",
            authorization_grant_type="authorization-code",
            registration_source="manual",
        )
        self.model = SimpleNamespace(DoesNotExist=LookupError)
        self.query = SimpleNamespace()
        self.query.select_related = lambda *args: self.query
        self.query.get = self.get_token
        self.token_row = SimpleNamespace(
            user_id=41,
            user=self.user,
            application_id=1,
            application=self.application,
            expires=timezone.now() + timedelta(minutes=10),
            resource=["https://mcp.example.test"],
            scope="character:self:read chronicle:read:self",
            is_expired=lambda: False,
        )

    def test_resource_uses_public_url_fallback_and_explicit_override(self):
        with override_settings(MCP_RESOURCE_URL="", MCP_PUBLIC_URL="https://public.example.test/mcp/"):
            self.assertEqual(auth.resource_url(), "https://public.example.test/mcp")
        with override_settings(
            MCP_RESOURCE_URL="https://override.example.test/mcp/", MCP_PUBLIC_URL="https://public.example.test"
        ):
            self.assertEqual(auth.resource_url(), "https://override.example.test/mcp")

    def get_token(self, **kwargs):
        import hashlib

        self.assertEqual(kwargs["token_checksum"], hashlib.sha256(b"secret-token").hexdigest())
        return self.token_row

    def verify(self):
        with (
            patch.object(auth, "get_access_token_model", return_value=self.model),
            patch.object(auth, "resource_url", return_value="https://mcp.example.test"),
            patch.object(auth, "issuer_url", return_value="https://game.example.test/o"),
        ):
            return auth._resolve_token("secret-token")

    def test_valid_dot_token_is_bound_to_user_issuer_and_resource(self):
        self.model.objects = self.query
        token = self.verify()
        self.assertEqual(token.subject, "41")
        self.assertEqual(token.resource, "https://mcp.example.test")
        self.assertEqual(token.claims["iss"], "https://game.example.test/o")
        self.assertEqual(token.scopes, ["character:self:read", "chronicle:read:self"])
        self.assertEqual(token.token, "")
        self.assertNotIn("secret-token", repr(token))

    def test_wrong_audience_expiry_revocation_user_and_unknown_scope_are_denied(self):
        self.model.objects = self.query
        self.token_row.resource = ["https://mcp.example.test", "https://other.example.test"]
        self.assertIsNone(self.verify())
        self.token_row.resource = ["https://other.example.test"]
        self.assertIsNone(self.verify())
        self.token_row.resource = ["https://mcp.example.test"]
        self.token_row.is_expired = lambda: True
        self.assertIsNone(self.verify())
        self.token_row.is_expired = lambda: False
        self.token_row.user.is_active = False
        self.assertIsNone(self.verify())
        self.token_row.user.is_active = True
        self.application.authorization_grant_type = "implicit"
        self.assertIsNone(self.verify())
        self.application.authorization_grant_type = "authorization-code"
        self.application.registration_source = "dcr"
        self.assertIsNone(self.verify())
        self.application.registration_source = "manual"
        self.token_row.scope += " admin:write"
        self.assertIsNone(self.verify())
        self.query.get = lambda **kwargs: (_ for _ in ()).throw(LookupError())
        self.assertIsNone(self.verify())


class AsyncVerifierTests(IsolatedAsyncioTestCase):
    async def test_verifier_runs_dot_lookup_in_thread_sensitive_adapter(self):
        token = AccessToken(token="opaque", client_id="c", scopes=[], resource="https://mcp.example.test")

        async def run_in_thread(_token):
            return token

        with (
            patch.object(auth, "issuer_url", return_value="https://game.example.test"),
            patch.object(auth, "resource_url", return_value="https://mcp.example.test"),
            patch.object(auth, "sync_to_async", return_value=run_in_thread) as adapter,
        ):
            self.assertIs(await auth.DjangoAccessTokenVerifier().verify_token("opaque"), token)
        adapter.assert_called_once_with(auth._resolve_token, thread_sensitive=True)


class ToolSurfaceTests(SimpleTestCase):
    @override_settings(MCP_OAUTH_ISSUER="https://game.example.test/o", MCP_RESOURCE_URL="https://mcp.example.test")
    def test_exactly_five_tools_and_scope_denial(self):
        server = FastMCP("test")
        register_tools(server)
        names = {tool.name for tool in server._tool_manager.list_tools()}
        self.assertEqual(
            names,
            {
                "get_my_character_summary",
                "get_my_status_and_boons",
                "get_public_chronicle",
                "get_my_chronicle",
                "get_public_lore",
            },
        )
        token = _valid_access_token(["lore:read:public"])
        marker = auth_context_var.set(AuthenticatedUser(token))
        try:
            with self.assertRaises(ToolError):
                _require_token(SimpleNamespace(), "character:self:read")
            self.assertEqual(_require_token(SimpleNamespace(), "lore:read:public"), token)
        finally:
            auth_context_var.reset(marker)

    @override_settings(MCP_OAUTH_ISSUER="https://game.example.test/o", MCP_RESOURCE_URL="https://mcp.example.test")
    def test_token_context_rechecks_issuer_resource_expiry_and_subject(self):
        token = _valid_access_token(["lore:read:public"])
        marker = auth_context_var.set(AuthenticatedUser(token))
        try:
            self.assertIs(_require_token(SimpleNamespace(), "lore:read:public"), token)
            token.claims["iss"] = "https://attacker.example.test"
            with self.assertRaises(ToolError):
                _require_token(SimpleNamespace(), "lore:read:public")
            token.claims["iss"] = "https://game.example.test/o"
            token.resource = "https://other.example.test"
            with self.assertRaises(ToolError):
                _require_token(SimpleNamespace(), "lore:read:public")
            token.resource = "https://mcp.example.test"
            token.expires_at = int(time.time()) - 1
            with self.assertRaises(ToolError):
                _require_token(SimpleNamespace(), "lore:read:public")
            token.expires_at = int(time.time()) + 60
            token.subject = "not-a-user"
            with self.assertRaises(ToolError):
                _require_token(SimpleNamespace(), "lore:read:public")
        finally:
            auth_context_var.reset(marker)


class AsyncToolSurfaceTests(IsolatedAsyncioTestCase):
    @override_settings(MCP_OAUTH_ISSUER="https://game.example.test/o", MCP_RESOURCE_URL="https://mcp.example.test")
    async def test_foreign_character_is_not_found_and_owner_id_is_not_an_argument(self):
        from .tools import register_tools

        server = FastMCP("test")
        register_tools(server)
        tool = server._tool_manager.get_tool("get_my_character_summary")
        self.assertEqual(set(tool.parameters["properties"]), {"character_id"})
        token = _valid_access_token(["character:self:read"])
        marker = auth_context_var.set(AuthenticatedUser(token))
        try:
            account = SimpleNamespace(pk=41)
            with (
                patch("mcp_server.tools.current_user", new=AsyncMock(return_value=account)),
                patch("chronicle.read_services.character_summary_for_account", return_value=None) as read_summary,
            ):
                with self.assertRaises(ToolError) as error:
                    await tool.fn(character_id=999, ctx=SimpleNamespace())
                self.assertEqual(str(error.exception), "Character not found.")
                read_summary.assert_called_once_with(account, 999)
        finally:
            auth_context_var.reset(marker)

    @override_settings(MCP_OAUTH_ISSUER="https://game.example.test/o", MCP_RESOURCE_URL="https://mcp.example.test")
    async def test_valid_character_call_uses_thread_sensitive_read_adapter(self):
        from asgiref.sync import sync_to_async as real_sync_to_async

        server = FastMCP("test")
        register_tools(server)
        tool = server._tool_manager.get_tool("get_my_character_summary")
        token = _valid_access_token(["character:self:read"])
        marker = auth_context_var.set(AuthenticatedUser(token))
        account = SimpleNamespace(pk=41)
        summary = {"id": 112, "name": "Caller-owned"}
        try:
            with (
                patch("mcp_server.tools.current_user", new=AsyncMock(return_value=account)),
                patch("chronicle.read_services.character_summary_for_account", return_value=summary) as read_summary,
                patch("mcp_server.tools.sync_to_async", wraps=real_sync_to_async) as adapter,
            ):
                result = await tool.fn(character_id=112, ctx=SimpleNamespace())
            self.assertEqual(result, summary)
            read_summary.assert_called_once_with(account, 112)
            adapter.assert_called_once_with(read_summary, thread_sensitive=True)
        finally:
            auth_context_var.reset(marker)


class RequestProtectionTests(IsolatedAsyncioTestCase):
    async def _request(self, *, host="mcp.example.test", origin=None, method="POST"):
        sent = []

        async def app(scope, receive, send):
            sent.append(("app", scope["method"]))
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = RequestProtection(app, ("mcp.example.test",), ("https://player.example.test",))
        headers = [(b"host", host.encode())]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await middleware({"type": "http", "method": method, "headers": headers}, receive, send)
        return messages[0]["status"], sent

    async def test_host_origin_and_allowed_non_browser_client(self):
        status, calls = await self._request(origin="https://player.example.test")
        self.assertEqual(status, 204)
        self.assertEqual(len(calls), 1)
        status, calls = await self._request(origin=None)
        self.assertEqual(status, 204)
        self.assertEqual(len(calls), 1)
        status, calls = await self._request(origin="https://evil.example.test")
        self.assertEqual(status, 403)
        self.assertEqual(calls, [])
        status, calls = await self._request(host="mcp.example.test.evil.test")
        self.assertEqual(status, 403)
        self.assertEqual(calls, [])

    async def test_mutating_or_unsupported_methods_are_denied(self):
        status, calls = await self._request(method="PUT")
        self.assertEqual(status, 405)
        self.assertEqual(calls, [])


class MCPAccountIsolationTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        CharacterBio.objects.create(character=self.char1, account=self.account, status="approved")
        CharacterBio.objects.create(character=self.char2, account=self.account2, status="approved")

    @override_settings(
        MCP_OAUTH_ISSUER="https://game.example.test/o",
        MCP_RESOURCE_URL="https://mcp.example.test",
    )
    def test_character_summary_is_limited_to_token_owner(self):
        server = FastMCP("test")
        register_tools(server)
        tool = server._tool_manager.get_tool("get_my_character_summary")
        token = _valid_access_token(["character:self:read"])
        token.subject = str(self.char1.account.pk)
        marker = auth_context_var.set(AuthenticatedUser(token))
        try:
            result = async_to_sync(tool.fn)(
                character_id=self.char1.pk,
                ctx=SimpleNamespace(),
            )
            self.assertEqual(result["id"], self.char1.pk)
            with self.assertRaises(ToolError):
                async_to_sync(tool.fn)(
                    character_id=self.char2.pk,
                    ctx=SimpleNamespace(),
                )
        finally:
            auth_context_var.reset(marker)


class OAuthDiscoveryTests(TestCase):
    def test_authorization_metadata_advertises_canonical_scopes_and_pkce(self):
        issuer = "https://game.example.test/o"
        provider_settings = {**settings.OAUTH2_PROVIDER, "OIDC_ISS_ENDPOINT": issuer}
        with override_settings(
            MCP_OAUTH_ISSUER=issuer,
            OAUTH2_PROVIDER=provider_settings,
        ):
            response = self.client.get("/.well-known/oauth-authorization-server/o")

        self.assertEqual(response.status_code, 200)
        metadata = response.json()
        self.assertEqual(metadata["issuer"], issuer)
        self.assertEqual(metadata["authorization_endpoint"], f"{issuer}/authorize/")
        self.assertEqual(metadata["token_endpoint"], f"{issuer}/token/")
        self.assertIn("S256", metadata["code_challenge_methods_supported"])
        self.assertNotIn("plain", metadata["code_challenge_methods_supported"])
        self.assertEqual(
            set(metadata["scopes_supported"]),
            {
                "character:self:read",
                "chronicle:read:public",
                "chronicle:read:self",
                "lore:read:public",
            },
        )
        self.assertNotIn("registration_endpoint", metadata)


class MCPApplicationConfigurationTests(SimpleTestCase):
    def test_remote_cleartext_authority_is_rejected(self):
        with (
            override_settings(
                MCP_OAUTH_ISSUER="http://game.example.test/o",
                MCP_RESOURCE_URL="https://mcp.example.test/mcp",
                MCP_ALLOWED_HOSTS=("mcp.example.test",),
            ),
            self.assertRaises(RuntimeError),
        ):
            create_application()

    def test_loopback_http_configuration_is_accepted(self):
        with override_settings(
            MCP_OAUTH_ISSUER="http://127.0.0.1:6665/o",
            MCP_RESOURCE_URL="http://127.0.0.1:8001/mcp",
            MCP_ALLOWED_HOSTS=("127.0.0.1:8001",),
        ):
            self.assertIsNotNone(create_application())


class MCPTransportIntegrationTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        CharacterBio.objects.create(character=self.char1, account=self.account, status="approved")
        CharacterBio.objects.create(character=self.char2, account=self.account2, status="approved")

    @override_settings(
        MCP_OAUTH_ISSUER="https://game.example.test/o",
        MCP_RESOURCE_URL="https://mcp.example.test/mcp",
        MCP_ALLOWED_HOSTS=("mcp.example.test",),
    )
    def test_sdk_reads_owned_character_and_denies_other_account(self):
        raw_token = "mcp-integration-test-token"
        application = OAuthApplication.objects.create(
            user=self.char1.account,
            name="MCP integration test",
            client_id="mcp-integration-test",
            client_secret="test-secret",
            client_type="confidential",
            authorization_grant_type="authorization-code",
            redirect_uris="https://client.example.test/callback",
        )
        token = OAuthAccessToken(
            user=self.char1.account,
            application=application,
            expires=timezone.now() + timedelta(minutes=5),
            scope="character:self:read lore:read:public",
            resource=["https://mcp.example.test/mcp"],
        )
        set_token_value(token, raw_token)
        token.save()
        app = create_application()

        async def exercise_client():
            starlette_app = app.app
            async with (
                starlette_app.router.lifespan_context(starlette_app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://mcp.example.test",
                    headers={"Authorization": f"Bearer {raw_token}"},
                ) as http_client,
                streamable_http_client(
                    "https://mcp.example.test/mcp",
                    http_client=http_client,
                ) as (read_stream, write_stream, _),
                ClientSession(read_stream, write_stream) as session,
            ):
                resource_response = await http_client.get("/.well-known/oauth-protected-resource/mcp")
                self.assertEqual(resource_response.status_code, 200)
                resource_metadata = resource_response.json()
                await session.initialize()
                own = await session.call_tool(
                    "get_my_character_summary",
                    {"character_id": self.char1.pk},
                )
                other = await session.call_tool(
                    "get_my_character_summary",
                    {"character_id": self.char2.pk},
                )
                lore = await session.call_tool("get_public_lore", {})
                return own, other, lore, resource_metadata

        own, other, lore, resource_metadata = async_to_sync(exercise_client)()
        self.assertFalse(own.isError)
        self.assertEqual(json.loads(own.content[0].text)["id"], self.char1.pk)
        self.assertTrue(other.isError)
        self.assertEqual(resource_metadata["resource"], "https://mcp.example.test/mcp")
        self.assertEqual(resource_metadata["authorization_servers"], ["https://game.example.test/o"])
        self.assertFalse(lore.isError)
        self.assertEqual(
            set(json.loads(lore.content[0].text)),
            {
                "attributes",
                "skills",
                "clans",
                "disciplines",
                "predator_types",
                "backgrounds",
                "blood_potency",
                "resonances",
            },
        )


class OAuthApplicationRegistrationTests(TestCase):
    def test_registration_requires_evennia_builder_not_django_staff(self):
        user_model = get_user_model()
        player = user_model.objects.create_user(username="oauth-player", password="test")
        staff = user_model.objects.create_user(username="oauth-staff", password="test", is_staff=True)

        self.client.force_login(player)
        for url in (
            "/o/applications/",
            "/o/applications/register/",
            "/o/applications/1/",
            "/o/applications/1/delete/",
            "/o/applications/1/update/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post("/o/applications/register/").status_code, 403)
        self.assertFalse(OAuthApplication.objects.filter(user=player).exists())

        self.client.force_login(staff)
        self.assertEqual(self.client.get("/o/applications/").status_code, 403)
        self.assertEqual(self.client.post("/o/applications/register/").status_code, 403)
        staff.permissions.add("Builder")
        self.assertEqual(self.client.get("/o/applications/").status_code, 200)
        self.assertEqual(self.client.get("/o/applications/register/").status_code, 200)
