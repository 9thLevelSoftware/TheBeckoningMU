from __future__ import annotations

import hashlib

from asgiref.sync import sync_to_async
from django.conf import settings
from mcp.server.auth.provider import AccessToken
from oauth2_provider.models import get_access_token_model

OAUTH_SCOPES = (
    "character:self:read",
    "chronicle:read:public",
    "chronicle:read:self",
    "lore:read:public",
)


def resource_url() -> str:
    override = getattr(settings, "MCP_RESOURCE_URL", "") or ""
    canonical = getattr(settings, "MCP_PUBLIC_URL", "") or ""
    return (override or canonical).rstrip("/")


def issuer_url() -> str:
    return getattr(settings, "MCP_OAUTH_ISSUER", "").rstrip("/")


def _resolve_token(raw_token: str):
    """Load a currently valid token without relying on plaintext token storage."""
    if not raw_token or len(raw_token) > 4096:
        return None
    model = get_access_token_model()
    try:
        token = model.objects.select_related("user", "application").get(
            token_checksum=hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        )
    except model.DoesNotExist:
        return None
    if token.is_expired() or not token.user_id or not token.user.is_active:
        return None
    if not token.application_id or not token.application:
        return None
    if token.application.authorization_grant_type != "authorization-code":
        return None
    if token.application.registration_source != "manual":
        return None
    expected_resource = resource_url()
    resources = token.resource if isinstance(token.resource, list) else []
    if not expected_resource or resources != [expected_resource]:
        return None
    token_scopes = set(token.scope.split())
    if not token_scopes.issubset(OAUTH_SCOPES):
        return None
    return AccessToken(
        token="",
        client_id=token.application.client_id,
        scopes=sorted(token_scopes),
        expires_at=int(token.expires.timestamp()) if token.expires else None,
        resource=expected_resource,
        subject=str(token.user_id),
        claims={"iss": issuer_url()},
    )


class DjangoAccessTokenVerifier:
    """Validate opaque DOT tokens against the live Django token authority."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not issuer_url() or not resource_url():
            return None
        return await sync_to_async(_resolve_token, thread_sensitive=True)(token)


def token_user(token: AccessToken):
    """Resolve a verified OAuth subject back to its active Django user."""
    from django.contrib.auth import get_user_model

    try:
        user_id = int(token.subject or "")
    except (TypeError, ValueError):
        return None
    user_model = get_user_model()
    return user_model.objects.filter(pk=user_id, is_active=True).first()


async def current_user(token: AccessToken):
    return await sync_to_async(token_user, thread_sensitive=True)(token)
