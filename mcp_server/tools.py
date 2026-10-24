from __future__ import annotations

import time

from asgiref.sync import sync_to_async
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .auth import OAUTH_SCOPES, current_user, issuer_url, resource_url


def _require_token(ctx: Context, scope: str):
    token = get_access_token()
    if (
        token is None
        or token.claims is None
        or token.claims.get("iss") != issuer_url()
        or token.resource != resource_url()
        or token.expires_at is None
        or token.expires_at <= time.time()
        or not token.subject
        or not token.subject.isdecimal()
        or not set(token.scopes).issubset(OAUTH_SCOPES)
        or scope not in token.scopes
    ):
        raise ToolError("The access token does not grant the required permission.")
    return token


def _public_chronicle_records(limit: int) -> list[dict]:
    from chronicle.read_services import public_chronicle

    return [
        record
        for event in public_chronicle(limit=_bounded_limit(limit))
        if (record := _chronicle_record(event)) is not None
    ]


def _account_chronicle_records(account, limit: int) -> list[dict]:
    from chronicle.read_services import account_chronicle

    events = account_chronicle(account, limit=_bounded_limit(limit))
    return [record for event in events if (record := _chronicle_record(event, "account", account)) is not None]


def _chronicle_record(event, audience="public", account=None):
    from chronicle.services import event_projection

    record = event_projection(event, audience, account)
    if record is None:
        return None
    return {key: record[key] for key in ("id", "kind", "title", "summary", "occurred_at")}


def register_tools(server: FastMCP) -> None:
    @server.tool()
    async def get_my_character_summary(character_id: int, ctx: Context) -> dict:
        """Get the authenticated player's authorized summary for one owned character."""
        token = _require_token(ctx, "character:self:read")
        user = await current_user(token)
        if user is None:
            raise ToolError("Character not found.")
        from chronicle.read_services import character_summary_for_account

        summary = await sync_to_async(character_summary_for_account, thread_sensitive=True)(user, character_id)
        if summary is None:
            raise ToolError("Character not found.")
        return summary

    @server.tool()
    async def get_my_status_and_boons(character_id: int, ctx: Context) -> dict:
        """Get status and boon totals for one character owned by the caller."""
        token = _require_token(ctx, "character:self:read")
        user = await current_user(token)
        if user is None:
            raise ToolError("Character not found.")
        from chronicle.read_services import character_summary_for_account

        summary = await sync_to_async(character_summary_for_account, thread_sensitive=True)(user, character_id)
        if summary is None:
            raise ToolError("Character not found.")
        return {"character_id": summary["id"], "status": summary["status"], "boons": summary["boons"]}

    @server.tool()
    async def get_public_chronicle(ctx: Context, limit: int = 50) -> list[dict]:
        """Read published public Chronicle events."""
        _require_token(ctx, "chronicle:read:public")
        records = await sync_to_async(_public_chronicle_records, thread_sensitive=True)(limit)
        return records

    @server.tool()
    async def get_my_chronicle(ctx: Context, limit: int = 50) -> list[dict]:
        """Read public and participant-visible Chronicle events for the caller."""
        token = _require_token(ctx, "chronicle:read:self")
        user = await current_user(token)
        if user is None:
            raise ToolError("No Chronicle events are available.")
        return await sync_to_async(_account_chronicle_records, thread_sensitive=True)(user, limit)

    @server.tool()
    async def get_public_lore(ctx: Context) -> dict:
        """Read the allowlisted public V5 reference lore."""
        _require_token(ctx, "lore:read:public")
        from chronicle.read_services import public_lore

        return await sync_to_async(public_lore, thread_sensitive=True)()


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit), 100))
