"""Keep DOT's protocol behavior; arbitrate final MCP grant persistence."""

import hashlib

from django.db.models import F
from oauth2_provider.models import get_access_token_model, get_grant_model, get_refresh_token_model
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from .oauth_guard import is_mcp_grant, mcp_account_grant_guard


class MCPOAuth2Validator(OAuth2Validator):
    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        # Capture resource identity before validation. A later logout can delete
        # the grant; an omitted token-request resource must not bypass the guard.
        resources = (
            get_grant_model().objects.filter(code=code, application=client).values_list("resource", flat=True).first()
        )
        valid = super().validate_code(client_id, code, client, request, *args, **kwargs)
        request._validated_mcp_code = valid and is_mcp_grant(client, resources)
        return valid

    def validate_refresh_token(self, raw, client, request, *args, **kwargs):
        # DOT may revoke the family during reuse validation. Arbitrate that
        # revocation with final issuance too, not just the explicit revoke route.
        source = (
            get_refresh_token_model()
            .objects.filter(token_checksum=hashlib.sha256(raw.encode("utf-8")).hexdigest())
            .order_by(F("revoked").desc(nulls_first=True))
            .first()
        )
        if source is not None and is_mcp_grant(client, source.resource):
            if source.application_id != getattr(client, "pk", None):
                return False
            with mcp_account_grant_guard(source.user_id) as exists:
                return exists and super().validate_refresh_token(raw, client, request, *args, **kwargs)
        return super().validate_refresh_token(raw, client, request, *args, **kwargs)

    def _save_bearer_token(self, token, request, *args, **kwargs):
        # DOT calls this documented extension hook inside save_bearer_token's
        # transaction. Earlier protocol validation is only a cached snapshot.
        source = getattr(request, "refresh_token_instance", None)
        guarded = (
            getattr(request, "_validated_mcp_code", False)
            or is_mcp_grant(request.client, getattr(request, "resource", None))
            or is_mcp_grant(request.client, getattr(source, "resource", None))
        )
        if not guarded:
            return super()._save_bearer_token(token, request, *args, **kwargs)

        account_id = getattr(request.user, "pk", None)
        with mcp_account_grant_guard(account_id) as exists:
            if not exists:
                raise InvalidGrantError(request=request)
            if request.grant_type == "refresh_token":
                valid = super().validate_refresh_token(request.refresh_token, request.client, request)
            elif request.grant_type == "authorization_code":
                valid = super().validate_code(request.client_id, request.code, request.client, request)
            else:
                valid = False
            if not valid or request.user.pk != account_id:
                raise InvalidGrantError(request=request)

            result = super()._save_bearer_token(token, request, *args, **kwargs)
            if request.grant_type == "authorization_code":
                # Consume in the same transaction as issuance, so neither logout
                # nor a second redemption can slip between save and consumption.
                super().invalidate_authorization_code(request.client_id, request.code, request)
                request._mcp_code_consumed = True
            return result

    def invalidate_authorization_code(self, client_id, code, request, *args, **kwargs):
        if not getattr(request, "_mcp_code_consumed", False):
            return super().invalidate_authorization_code(client_id, code, request, *args, **kwargs)

    def revoke_token(self, raw, token_type_hint, request, *args, **kwargs):
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        client = getattr(request, "client", None)
        for model in (get_access_token_model(), get_refresh_token_model()):
            for source in model.objects.filter(token_checksum=checksum, application_id=getattr(client, "pk", None)):
                if is_mcp_grant(client, source.resource):
                    with mcp_account_grant_guard(source.user_id):
                        return super().revoke_token(raw, token_type_hint, request, *args, **kwargs)
        return super().revoke_token(raw, token_type_hint, request, *args, **kwargs)
