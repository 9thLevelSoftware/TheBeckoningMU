"""Website sign-out ends the account's grants to this MCP resource."""

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from oauth2_provider.models import get_access_token_model, get_grant_model, get_refresh_token_model

from .auth import resource_url
from .oauth_guard import mcp_account_grant_guard


@receiver(user_logged_out, dispatch_uid="mcp_server.revoke_on_website_logout")
def revoke_mcp_grants_on_logout(sender, request, user, **kwargs):
    resource = resource_url()
    if user is None or not user.is_authenticated or not resource:
        return
    # Match the same controlled client policy as the MCP verifier. Other users'
    # tokens, other resources and non-MCP OAuth clients remain independent.
    filters = {
        "user_id": user.pk,
        "application__authorization_grant_type": "authorization-code",
        "application__registration_source": "manual",
    }

    def matches(record):
        return isinstance(record.resource, list) and resource in record.resource

    with mcp_account_grant_guard(user.pk) as exists:
        if not exists:
            return
        # Lock refresh rows before access rows, as DOT's rotation/revocation does.
        # Re-read the access rows after revocation, including access-only grants.
        for token in get_refresh_token_model().objects.select_for_update().filter(**filters):
            if matches(token):
                token.revoke()
        for token in get_access_token_model().objects.select_for_update().filter(**filters):
            if matches(token):
                token.revoke()
        for grant in get_grant_model().objects.select_for_update().filter(**filters):
            if matches(grant):
                grant.delete()
