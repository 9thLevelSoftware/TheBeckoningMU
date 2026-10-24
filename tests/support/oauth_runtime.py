"""Owned loopback OAuth/SDK fixture; no live DB, provider, or remote network.

One process owns its temporary database, prebound OS-selected socket and Uvicorn
task. All HTTP clients reject URLs outside that exact socket before dispatch.
The consent browser uses a fixture login cookie but the real CSRF-protected DOT
authorization endpoints and real HTTP callback. DCR/CIMD remain disabled.
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import socket
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.support.local_runtime import bootstrap, fixtures, initialize  # noqa: E402


class FixtureStorage:
    """Fixture-local memory; no credentials written to disk or printed."""

    def __init__(self, client_info):
        self.client_info = client_info
        self.tokens = None
        self.writes = []

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens
        self.writes.append(tokens)

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        raise AssertionError("Controlled registration must not be replaced by DCR/CIMD")


async def qualify(database, listener):
    import httpx
    import uvicorn
    from django.conf import settings
    from django.core.asgi import get_asgi_application
    from django.test import Client
    from django.utils import timezone
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.auth.exceptions import OAuthFlowError
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
    from oauth2_provider.models import AccessToken, Application
    from starlette.responses import JSONResponse, PlainTextResponse

    from mcp_server.app import create_application
    from mcp_server.auth import OAUTH_SCOPES

    accounts, characters = fixtures()
    port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    issuer, resource, callback = origin + "/o", origin + "/mcp", origin + "/callback"
    settings.ALLOWED_HOSTS = ["127.0.0.1"]
    settings.MCP_OAUTH_ISSUER = issuer
    settings.MCP_RESOURCE_URL = resource
    settings.MCP_ALLOWED_HOSTS = (f"127.0.0.1:{port}",)
    settings.MCP_ALLOWED_ORIGINS = (origin,)
    settings.OAUTH2_PROVIDER = {
        **settings.OAUTH2_PROVIDER,
        "OIDC_ISS_ENDPOINT": issuer,
        "ALWAYS_RELOAD_OAUTHLIB_CORE": True,
        "DCR_ENABLED": False,
        "CIMD_ENABLED": False,
    }
    application = Application.objects.create(
        user=accounts[0],
        name="Manual loopback SDK fixture",
        client_type="public",
        authorization_grant_type="authorization-code",
        redirect_uris=callback,
    )
    assert application.registration_source == "manual"
    mcp = create_application()
    django_app = get_asgi_application()
    callbacks, requests = [], []
    mode = "normal"

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            await mcp(scope, receive, send)
            return
        path = scope["path"]
        requests.append((scope["method"], path))
        if path == "/callback":
            callbacks.append(parse_qs(scope["query_string"].decode()))
            await PlainTextResponse("Fixture callback received")(scope, receive, send)
        elif mode == "resource" and path == "/.well-known/oauth-protected-resource/mcp":
            await JSONResponse({"resource": origin + "/foreign", "authorization_servers": [issuer]})(
                scope, receive, send
            )
        elif mode == "issuer" and path.startswith("/.well-known/oauth-authorization-server"):
            await JSONResponse(
                {
                    "issuer": origin + "/wrong-issuer",
                    "authorization_endpoint": issuer + "/authorize/",
                    "token_endpoint": issuer + "/token/",
                    "response_types_supported": ["code"],
                }
            )(scope, receive, send)
        elif path == "/mcp" or path.startswith("/.well-known/oauth-protected-resource"):
            await mcp(scope, receive, send)
        else:
            await django_app(scope, receive, send)

    config = uvicorn.Config(app, log_level="error", access_log=False, lifespan="on", timeout_graceful_shutdown=3)
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve(sockets=[listener]))

    async def local_only(request):
        parsed = urlsplit(str(request.url))
        assert parsed.scheme == "http" and parsed.netloc == f"127.0.0.1:{port}", "Non-fixture HTTP refused"

    http_options = {"timeout": 8, "trust_env": False, "event_hooks": {"request": [local_only]}}

    def make_provider(account, *, bad_state=False):
        browser_login = Client()
        browser_login.force_login(account)
        cookie = browser_login.cookies[settings.SESSION_COOKIE_NAME].value
        storage = FixtureStorage(
            OAuthClientInformationFull(
                client_id=application.client_id,
                redirect_uris=[callback],
                token_endpoint_auth_method="none",
                scope=" ".join(OAUTH_SCOPES),
                issuer=issuer,
            )
        )
        observed = {}

        async def redirect_handler(url):
            parsed = urlsplit(url)
            assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == issuer + "/authorize/"
            parameters = parse_qs(parsed.query)
            assert parameters["resource"] == [resource]
            assert parameters["redirect_uri"] == [callback]
            assert parameters["code_challenge_method"] == ["S256"]
            assert len(parameters["code_challenge"][0]) == 43 and parameters["state"][0]
            observed.update(parameters)
            async with httpx.AsyncClient(**http_options) as browser:
                browser.cookies.set(settings.SESSION_COOKIE_NAME, cookie, domain="127.0.0.1")
                consent = await browser.get(url)
                assert consent.status_code == 200, consent.status_code
                csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', consent.text)
                assert csrf, "Real consent form must provide CSRF token"
                fields = {key: values[0] for key, values in parameters.items()}
                response = await browser.post(
                    issuer + "/authorize/",
                    data={**fields, "allow": "Authorize", "csrfmiddlewaretoken": csrf.group(1)},
                )
                assert response.status_code == 302, response.text[:300]
                location = response.headers["location"]
                parsed_callback = urlsplit(location)
                assert f"{parsed_callback.scheme}://{parsed_callback.netloc}{parsed_callback.path}" == callback
                returned = parse_qs(parsed_callback.query)
                assert returned["iss"] == [issuer] and returned["state"] == parameters["state"]
                assert (await browser.get(location)).status_code == 200

        async def callback_handler():
            returned = callbacks.pop()
            return returned["code"][0], "wrong-state" if bad_state else returned["state"][0]

        async def inspect_exchange(request):
            await local_only(request)
            if request.url.path == "/o/token/":
                fields = parse_qs((await request.aread()).decode())
                assert fields["resource"] == [resource]
                assert fields["client_id"] == [application.client_id]
                if fields["grant_type"] == ["authorization_code"]:
                    verifier = fields["code_verifier"][0]
                    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                    assert observed["code_challenge"] == [digest]
                    assert fields["redirect_uri"] == [callback]

        provider = OAuthClientProvider(
            server_url=resource,
            client_metadata=OAuthClientMetadata(
                redirect_uris=[callback], token_endpoint_auth_method="none", scope=" ".join(OAUTH_SCOPES)
            ),
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=8,
        )
        options = {**http_options, "event_hooks": {"request": [inspect_exchange]}}
        return provider, storage, options

    try:
        async with asyncio.timeout(8):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)

        async with httpx.AsyncClient(**http_options) as http:
            challenge = await http.post(resource, json={})
            assert challenge.status_code == 401
            assert origin + "/.well-known/oauth-protected-resource/mcp" in challenge.headers["www-authenticate"]
            discovery = (await http.get(origin + "/.well-known/oauth-protected-resource/mcp")).json()
            assert discovery["resource"] == resource and discovery["authorization_servers"] == [issuer]
            metadata = (await http.get(origin + "/.well-known/oauth-authorization-server/o")).json()
            assert metadata["issuer"] == issuer
            assert metadata["authorization_endpoint"] == issuer + "/authorize/"
            assert metadata["token_endpoint"] == issuer + "/token/"
            assert "registration_endpoint" not in metadata
            assert (await http.post(resource, json={}, headers={"Host": "foreign.test"})).status_code == 403
            assert (await http.post(resource, json={}, headers={"Origin": "https://foreign.test"})).status_code == 403

        refreshes = 0
        for account, own, foreign in (
            (accounts[0], characters[0], characters[1]),
            (accounts[1], characters[1], characters[0]),
        ):
            provider, storage, options = make_provider(account)
            async with (
                httpx.AsyncClient(auth=provider, **options) as http,
                streamable_http_client(resource, http_client=http) as (read, send, _),
                ClientSession(read, send) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
                assert {tool.name for tool in listed.tools} == {
                    "get_my_character_summary",
                    "get_my_status_and_boons",
                    "get_public_chronicle",
                    "get_my_chronicle",
                    "get_public_lore",
                }
                for tool in ("get_my_character_summary", "get_my_status_and_boons"):
                    assert not (await session.call_tool(tool, {"character_id": own.pk})).isError
                    assert (await session.call_tool(tool, {"character_id": foreign.pk})).isError
                for tool in ("get_public_chronicle", "get_my_chronicle", "get_public_lore"):
                    assert not (await session.call_tool(tool, {})).isError
                assert (await session.call_tool("execute_command", {"command": "+hunt"})).isError
                original = storage.tokens
                AccessToken.objects.filter(
                    token_checksum=hashlib.sha256(original.access_token.encode()).hexdigest()
                ).update(expires=timezone.now() - timedelta(seconds=1))
                provider.context.token_expiry_time = time.time() - 1
                assert not (await session.call_tool("get_my_character_summary", {"character_id": own.pk})).isError
                assert len(storage.writes) == 2
                assert storage.tokens.access_token != original.access_token
                assert storage.tokens.refresh_token != original.refresh_token
                assert set(storage.tokens.scope.split()) == set(OAUTH_SCOPES)
                refreshes += 1
                async with httpx.AsyncClient(**http_options) as unauthenticated:
                    revoked = await unauthenticated.post(
                        issuer + "/revoke_token/",
                        data={
                            "client_id": application.client_id,
                            "token": storage.tokens.refresh_token,
                            "token_type_hint": "refresh_token",
                        },
                    )
                    assert revoked.status_code == 200
                    denied = await unauthenticated.post(
                        resource, json={}, headers={"Authorization": "Bearer " + storage.tokens.access_token}
                    )
                    assert denied.status_code == 401
                    denied_refresh = await unauthenticated.post(
                        issuer + "/token/",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": application.client_id,
                            "refresh_token": storage.tokens.refresh_token,
                            "resource": resource,
                        },
                    )
                    assert denied_refresh.status_code == 400 and denied_refresh.json()["error"] == "invalid_grant"

        for failure in ("state", "issuer", "resource"):
            mode = failure
            before = sum(path == "/o/token/" for _, path in requests)
            provider, storage, options = make_provider(accounts[0], bad_state=failure == "state")
            try:
                async with httpx.AsyncClient(auth=provider, **options) as http:
                    await http.post(resource, json={})
            except OAuthFlowError as error:
                assert failure in str(error).lower(), (failure, str(error))
            else:
                raise AssertionError(f"SDK accepted invalid {failure}")
            assert not storage.writes
            assert sum(path == "/o/token/" for _, path in requests) == before
        assert not any(path.endswith("/register") or path.endswith("/register/") for _, path in requests)
        assert Application.objects.count() == 1
        print(
            json.dumps(
                {
                    "gate": "loopback-sdk-oauth",
                    "passed": True,
                    "pid": os.getpid(),
                    "accounts": 2,
                    "negative_flows": ["state", "issuer", "resource"],
                    "refreshes": refreshes,
                }
            )
        )
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, timeout=8)
        finally:
            listener.close()
            from asgiref.sync import sync_to_async
            from django.db import connections

            await sync_to_async(connections.close_all, thread_sensitive=True)()
            connections.close_all()


def main():
    with tempfile.TemporaryDirectory(prefix="beckoning-oauth-") as directory:
        database = Path(directory).resolve() / "acceptance.sqlite3"
        marker = database.parent / ".local-acceptance"
        marker.touch()
        assert database.parent.is_dir() and marker.is_file() and not database.exists()
        bootstrap(database)
        initialize()
        # Bind before handing the socket to the owned server task: no port race.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            listener.setblocking(False)
            try:
                asyncio.run(qualify(database, listener))
            finally:
                from django.db import connections

                connections.close_all()


if __name__ == "__main__":
    main()
