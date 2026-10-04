from __future__ import annotations

import os
from urllib.parse import urlsplit

from django.conf import settings
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import OAUTH_SCOPES, DjangoAccessTokenVerifier, issuer_url, resource_url
from .tools import register_tools


def _configured_list(setting_name: str, env_name: str) -> tuple[str, ...]:
    configured = getattr(settings, setting_name, None)
    raw = configured if configured is not None else os.environ.get(env_name, "")
    values = raw.split(",") if isinstance(raw, str) else raw
    return tuple(value.strip() for value in values if isinstance(value, str) and value.strip())


def _origin_key(origin: str) -> str | None:
    try:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or "*" in parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None
        if parsed.path or parsed.query or parsed.fragment:
            return None
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    default_port = 443 if parsed.scheme == "https" else 80
    authority = host if port in (None, default_port) else f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{authority}"


def _host_key(host: str) -> str | None:
    if not host or any(character in host for character in " /\\\t\r\n,*"):
        return None
    try:
        parsed = urlsplit(f"//{host}")
        if not parsed.hostname or parsed.path or parsed.username or parsed.password:
            return None
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname.encode("idna").decode("ascii").lower()
    return hostname if port is None else f"{hostname}:{port}"


class RequestProtection:
    """Exact allowlists for host and optional browser Origin headers."""

    def __init__(self, app: ASGIApp, allowed_hosts: tuple[str, ...], allowed_origins: tuple[str, ...]):
        self.app = app
        self.allowed_hosts = frozenset(key for item in allowed_hosts if (key := _host_key(item)) is not None)
        self.allowed_origins = frozenset(key for item in allowed_origins if (key := _origin_key(item)) is not None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header_list = scope.get("headers", [])
        host_values = [value for key, value in header_list if key.lower() == b"host"]
        origin_values = [value for key, value in header_list if key.lower() == b"origin"]
        host = host_values[0].decode("latin-1") if len(host_values) == 1 else ""
        origin = origin_values[0] if len(origin_values) == 1 else None
        if len(origin_values) > 1:
            response = PlainTextResponse("Untrusted Origin", status_code=403)
            await response(scope, receive, send)
            return
        if not self.allowed_hosts or _host_key(host) not in self.allowed_hosts:
            response = PlainTextResponse("Untrusted Host", status_code=403)
            await response(scope, receive, send)
            return
        if origin is not None:
            raw_origin = origin.decode("latin-1")
            if not self.allowed_origins or _origin_key(raw_origin) not in self.allowed_origins:
                response = PlainTextResponse("Untrusted Origin", status_code=403)
                await response(scope, receive, send)
                return
        if scope.get("method") not in {"GET", "POST", "DELETE", "OPTIONS"}:
            response = PlainTextResponse(
                "Method Not Allowed", status_code=405, headers={"Allow": "GET, POST, DELETE, OPTIONS"}
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _is_absolute_http_url(value: str, *, allow_loopback_http: bool = True) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return False
    if parsed.scheme.lower() == "https":
        return True
    return allow_loopback_http and parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}


def create_application() -> ASGIApp:
    issuer = issuer_url()
    resource = resource_url()
    if not _is_absolute_http_url(issuer) or not _is_absolute_http_url(resource):
        raise RuntimeError("MCP_OAUTH_ISSUER and MCP_RESOURCE_URL must use HTTPS (loopback HTTP is allowed locally)")
    hosts = _configured_list("MCP_ALLOWED_HOSTS", "MCP_ALLOWED_HOSTS")
    origins = _configured_list("MCP_ALLOWED_ORIGINS", "MCP_ALLOWED_ORIGINS")
    server = FastMCP(
        name="Beckoning Chronicle MCP",
        instructions="Read-only public V5 lore and OAuth-account-scoped character and Chronicle data.",
        token_verifier=DjangoAccessTokenVerifier(),
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=resource,
            validate_token_resource=True,
            required_scopes=[],
        ),
        stateless_http=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    register_tools(server)
    app = server.streamable_http_app()
    metadata_route = create_protected_resource_routes(
        resource_url=server.settings.auth.resource_server_url,
        authorization_servers=[server.settings.auth.issuer_url],
        scopes_supported=list(OAUTH_SCOPES),
    )[0]
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != metadata_route.path]
    app.router.routes.append(metadata_route)
    return RequestProtection(app, hosts, origins)
