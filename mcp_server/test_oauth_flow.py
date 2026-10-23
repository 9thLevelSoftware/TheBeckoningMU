"""Exercise real local OAuth issuance before calling the MCP transport."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
from asgiref.sync import async_to_sync
from django.conf import settings
from django.test import override_settings
from evennia.utils.test_resources import EvenniaTest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from oauth2_provider.models import AccessToken, Application

from traits.models import CharacterBio

from .app import create_application
from .auth import OAUTH_SCOPES, _resolve_token

ISSUER = "https://game.example.test/o"
RESOURCE = "https://mcp.example.test/mcp"
REDIRECT = "https://client.example.test/callback"


@override_settings(
    MCP_OAUTH_ISSUER=ISSUER,
    MCP_RESOURCE_URL=RESOURCE,
    MCP_ALLOWED_HOSTS=("mcp.example.test",),
    OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_ISS_ENDPOINT": ISSUER},
)
class OAuthFlowTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        CharacterBio.objects.create(character=self.char1, account=self.account, status="approved")
        CharacterBio.objects.create(character=self.char2, account=self.account2, status="approved")
        self.application = Application.objects.create(
            user=self.account,
            name="Controlled local OAuth test client",
            client_type="public",
            authorization_grant_type="authorization-code",
            redirect_uris=REDIRECT,
        )
        self.verifier = "beckoning-pkce-verifier-for-local-tests-0123456789"

    def authorize(self, account):
        self.client.force_login(account)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        parameters = {
            "client_id": self.application.client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": " ".join(OAUTH_SCOPES),
            "state": "local-flow-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        }
        consent = self.client.get("/o/authorize/", parameters, secure=True)
        self.assertEqual(consent.status_code, 200)
        response = self.client.post("/o/authorize/", {**parameters, "allow": True}, secure=True)
        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(f"{location.scheme}://{location.netloc}{location.path}", REDIRECT)
        query = parse_qs(location.query)
        self.assertEqual(query["state"], ["local-flow-state"])
        self.assertEqual(query["iss"], [ISSUER])
        return query["code"][0]

    def exchange(self, code, **overrides):
        return self.client.post(
            "/o/token/",
            {
                "grant_type": "authorization_code",
                "client_id": self.application.client_id,
                "redirect_uri": REDIRECT,
                "code": code,
                "code_verifier": self.verifier,
                "resource": RESOURCE,
                **overrides,
            },
            secure=True,
        )

    def test_pkce_tokens_call_all_read_tools_as_two_accounts_and_revoke(self):
        tokens = []
        for character in (self.char1, self.char2):
            response = self.exchange(self.authorize(character.account))
            self.assertEqual(response.status_code, 200)
            raw_token = response.json()["access_token"]
            verified = _resolve_token(raw_token)
            self.assertEqual(verified.subject, str(character.account.pk))
            self.assertEqual(verified.resource, RESOURCE)
            tokens.append(raw_token)

        app = create_application()

        async def exercise():
            async with app.app.router.lifespan_context(app.app):
                for character, foreign, token in (
                    (self.char1, self.char2, tokens[0]),
                    (self.char2, self.char1, tokens[1]),
                ):
                    async with (
                        httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=app),
                            headers={"Authorization": f"Bearer {token}"},
                        ) as http_client,
                        streamable_http_client(RESOURCE, http_client=http_client) as (read, write, _),
                        ClientSession(read, write) as session,
                    ):
                        await session.initialize()
                        for tool in ("get_my_character_summary", "get_my_status_and_boons"):
                            own = await session.call_tool(tool, {"character_id": character.pk})
                            self.assertFalse(own.isError)
                            id_key = "id" if tool == "get_my_character_summary" else "character_id"
                            self.assertEqual(json.loads(own.content[0].text)[id_key], character.pk)
                            other = await session.call_tool(tool, {"character_id": foreign.pk})
                            self.assertTrue(other.isError)
                        for tool in ("get_public_chronicle", "get_my_chronicle", "get_public_lore"):
                            result = await session.call_tool(tool, {})
                            self.assertFalse(result.isError)
                        denied = await session.call_tool("execute_command", {"command": "+hunt"})
                        self.assertTrue(denied.isError)

        async_to_sync(exercise)()
        revoked = self.client.post(
            "/o/revoke_token/",
            {"client_id": self.application.client_id, "token": tokens[0], "token_type_hint": "access_token"},
            secure=True,
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertIsNone(_resolve_token(tokens[0]))
        self.assertIsNotNone(_resolve_token(tokens[1]))

    def test_wrong_pkce_verifier_cannot_exchange_code(self):
        response = self.exchange(self.authorize(self.char1.account), code_verifier="incorrect-verifier-" * 3)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")
        self.assertFalse(AccessToken.objects.exists())

    def test_token_exchange_cannot_widen_resource(self):
        response = self.exchange(self.authorize(self.char1.account), resource="https://foreign.example.test/mcp")
        self.assertEqual(response.status_code, 400)
        # DOT's exceptional resource-error response omits the JSON content type.
        self.assertEqual(json.loads(response.content)["error"], "invalid_target")
        self.assertFalse(AccessToken.objects.exists())
