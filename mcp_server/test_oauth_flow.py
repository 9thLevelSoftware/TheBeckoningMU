"""Exercise real local OAuth issuance before calling the MCP transport."""

import base64
import hashlib
import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from asgiref.sync import async_to_sync
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from oauth2_provider.models import AccessToken, Application, RefreshToken
from oauth2_provider.oauth2_validators import OAuth2Validator

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
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_ISS_ENDPOINT": ISSUER,
        "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
        "REFRESH_TOKEN_EXPIRE_SECONDS": 86400,
        "ROTATE_REFRESH_TOKEN": True,
        "REFRESH_TOKEN_REUSE_PROTECTION": True,
        "REFRESH_TOKEN_GRACE_PERIOD_SECONDS": 0,
        "ALWAYS_RELOAD_OAUTHLIB_CORE": True,
    },
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

    def authorize(self, account, scope=None):
        self.client.force_login(account)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        parameters = {
            "client_id": self.application.client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": " ".join(OAUTH_SCOPES) if scope is None else scope,
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

    def exchange(self, code, http_client=None, **overrides):
        return (http_client or self.client).post(
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

    def issue(self, scope=None):
        response = self.exchange(self.authorize(self.account, scope=scope))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def refresh(self, token, http_client=None, **overrides):
        return (http_client or self.client).post(
            "/o/token/",
            {
                "grant_type": "refresh_token",
                "client_id": self.application.client_id,
                "refresh_token": token,
                **overrides,
            },
            secure=True,
        )

    def refresh_record(self, raw):
        return RefreshToken.objects.get(token_checksum=hashlib.sha256(raw.encode()).hexdigest())

    def test_refresh_rotates_and_preserves_resource_scope_and_subject(self):
        original = self.issue()
        response = self.refresh(original["refresh_token"])
        self.assertEqual(response.status_code, 200, response.content)
        rotated = response.json()
        self.assertNotEqual(rotated["refresh_token"], original["refresh_token"])
        self.assertNotEqual(rotated["access_token"], original["access_token"])
        self.assertEqual(set(rotated["scope"].split()), set(OAUTH_SCOPES))
        old = self.refresh_record(original["refresh_token"])
        new = self.refresh_record(rotated["refresh_token"])
        self.assertIsNotNone(old.revoked)
        self.assertEqual(new.resource, [RESOURCE])
        self.assertEqual(new.token_family, old.token_family)
        self.assertIsNone(_resolve_token(original["access_token"]))
        verified = _resolve_token(rotated["access_token"])
        self.assertEqual(verified.resource, RESOURCE)
        self.assertEqual(verified.subject, str(self.account.pk))
        self.assertEqual(set(verified.scopes), set(OAUTH_SCOPES))

    def test_refresh_cannot_widen_scope_or_resource(self):
        original = self.issue(scope="character:self:read")
        for overrides, error in (
            ({"scope": "character:self:read chronicle:read:self"}, "invalid_scope"),
            ({"resource": "https://foreign.example.test/mcp"}, "invalid_target"),
        ):
            with self.subTest(overrides=overrides):
                response = self.refresh(original["refresh_token"], **overrides)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(json.loads(response.content)["error"], error)
                self.assertEqual(AccessToken.objects.count(), 1)
                self.assertIsNone(self.refresh_record(original["refresh_token"]).revoked)

    def test_refresh_replay_revokes_current_family(self):
        original = self.issue()
        rotated = self.refresh(original["refresh_token"]).json()
        # Establish the expired grace boundary without waiting on wall time.
        RefreshToken.objects.filter(pk=self.refresh_record(original["refresh_token"]).pk).update(
            revoked=timezone.now() - timedelta(seconds=1)
        )
        response = self.refresh(original["refresh_token"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")
        self.assertIsNone(_resolve_token(rotated["access_token"]))
        self.assertEqual(self.refresh(rotated["refresh_token"]).status_code, 400)

    def test_configured_access_and_refresh_expiry_are_enforced_without_cleanup(self):
        original = self.issue()
        record = self.refresh_record(original["refresh_token"])
        AccessToken.objects.filter(pk=record.access_token_id).update(expires=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(_resolve_token(original["access_token"]))
        # DOT's refresh lifetime is measured from the paired access expiry.
        AccessToken.objects.filter(pk=record.access_token_id).update(expires=timezone.now() - timedelta(days=2))
        response = self.refresh(original["refresh_token"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")
        self.assertEqual(RefreshToken.objects.count(), 1)

    def test_wrong_client_cannot_refresh_or_revoke_another_client_grant(self):
        original = self.issue()
        other = Application.objects.create(
            user=self.account2, name="Other client", client_type="public", authorization_grant_type="authorization-code"
        )
        response = self.refresh(original["refresh_token"], client_id=other.client_id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")
        response = self.client.post(
            "/o/revoke_token/",
            {"client_id": other.client_id, "token": original["refresh_token"], "token_type_hint": "refresh_token"},
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(_resolve_token(original["access_token"]))
        self.assertIsNone(self.refresh_record(original["refresh_token"]).revoked)

    def test_revocation_of_either_token_prevents_access_and_reissuance(self):
        for hint in ("access_token", "refresh_token"):
            with self.subTest(hint=hint):
                original = self.issue()
                response = self.client.post(
                    "/o/revoke_token/",
                    {"client_id": self.application.client_id, "token": original[hint], "token_type_hint": hint},
                    secure=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(_resolve_token(original["access_token"]))
                refreshed = self.refresh(original["refresh_token"])
                self.assertEqual(refreshed.status_code, 400)
                self.assertEqual(refreshed.json()["error"], "invalid_grant")

    def test_website_logout_revokes_only_this_accounts_mcp_grants(self):
        original = self.issue()
        other_response = self.exchange(self.authorize(self.account2))
        self.assertEqual(other_response.status_code, 200)
        other = other_response.json()
        unrelated = AccessToken.objects.create(
            user=self.account,
            application=self.application,
            token="unrelated-resource-access",
            expires=timezone.now() + timedelta(hours=1),
            scope="character:self:read",
            resource=["https://unrelated.example.test/api"],
        )
        unrelated_refresh = RefreshToken.objects.create(
            user=self.account,
            application=self.application,
            access_token=unrelated,
            token="unrelated-resource-refresh",
            resource=["https://unrelated.example.test/api"],
        )
        pending_code = self.authorize(self.account)
        response = self.client.post(reverse("logout"), secure=True)
        self.assertIn(response.status_code, (200, 302))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIsNone(_resolve_token(original["access_token"]))
        self.assertEqual(self.refresh(original["refresh_token"]).status_code, 400)
        self.assertEqual(self.exchange(pending_code).status_code, 400)
        self.assertIsNotNone(_resolve_token(other["access_token"]))
        self.assertEqual(self.refresh(other["refresh_token"]).status_code, 200)
        self.assertTrue(AccessToken.objects.filter(pk=unrelated.pk).exists())
        unrelated_refresh.refresh_from_db()
        self.assertIsNone(unrelated_refresh.revoked)

    def test_logout_after_validation_cannot_restore_refresh_or_code_grants(self):
        other = self.exchange(self.authorize(self.account2)).json()
        unrelated = AccessToken.objects.create(
            user=self.account,
            application=self.application,
            token="race-unrelated-access",
            expires=timezone.now() + timedelta(hours=1),
            scope="character:self:read",
            resource=["https://unrelated.example.test/api"],
        )
        unrelated_refresh = RefreshToken.objects.create(
            user=self.account,
            application=self.application,
            access_token=unrelated,
            token="race-unrelated-refresh",
            resource=unrelated.resource,
        )
        original_save = OAuth2Validator.save_bearer_token

        for grant_type in ("refresh_token", "authorization_code"):
            with self.subTest(grant_type=grant_type):
                original = self.issue()
                code = self.authorize(self.account) if grant_type == "authorization_code" else None
                # OAuth clients do not send the consent browser's session cookie
                # to the token endpoint. Otherwise SessionMiddleware can replace
                # the response when the nested logout deletes that browser session.
                token_client = self.client_class()
                attempted = []
                logged_out = False

                def logout_after_validation():
                    nonlocal logged_out
                    if not logged_out:
                        logged_out = True
                        response = self.client.post(reverse("logout"), secure=True)
                        self.assertIn(response.status_code, (200, 302))

                def observe_issuance(
                    validator,
                    token,
                    request,
                    *args,
                    attempted_tokens=attempted,
                    expected_grant_type=grant_type,
                    **kwargs,
                ):
                    attempted_tokens.append(dict(token))
                    if expected_grant_type == "refresh_token":
                        self.assertIsNone(request.refresh_token_instance.revoked)
                        self.assertEqual(request.refresh_token_instance.resource, [RESOURCE])
                    # All grant/scope/redirect/PKCE validation has completed. Keep
                    # DOT's cached objects and schedule logout before persistence.
                    logout_after_validation()
                    return original_save(validator, token, request, *args, **kwargs)

                with patch.object(OAuth2Validator, "save_bearer_token", observe_issuance):
                    response = (
                        self.exchange(code, http_client=token_client)
                        if code
                        else self.refresh(original["refresh_token"], http_client=token_client)
                    )

                self.assertTrue(logged_out)
                self.assertEqual(len(attempted), 1)
                # Check both the former pair and the generated successor values,
                # including orphan tokens even when DOT returns an error response.
                for pair in (original, attempted[0]):
                    self.assertIsNone(_resolve_token(pair["access_token"]))
                # Replay only after checking both access strings: DOT's family
                # reuse protection must not hide a successfully minted successor.
                for pair in (original, attempted[0]):
                    self.assertEqual(self.refresh(pair["refresh_token"]).status_code, 400)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(json.loads(response.content)["error"], "invalid_grant")
                self.assertIsNotNone(_resolve_token(other["access_token"]))
                self.assertTrue(AccessToken.objects.filter(pk=unrelated.pk).exists())
                unrelated_refresh.refresh_from_db()
                self.assertIsNone(unrelated_refresh.revoked)

        self.assertEqual(self.refresh(other["refresh_token"]).status_code, 200)
        self.assertEqual(
            self.refresh("race-unrelated-refresh", resource="https://unrelated.example.test/api").status_code, 200
        )
