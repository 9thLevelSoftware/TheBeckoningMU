"""Cross-process arbitration for issuance and revocation of MCP grants."""

from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.db import router, transaction
from django.db.models import F
from oauth2_provider.models import get_access_token_model

from .auth import resource_url


def is_mcp_grant(client, resources):
    resource = resource_url()
    if isinstance(resources, str):
        resources = [resources]
    return bool(
        resource
        and isinstance(resources, list)
        and resource in resources
        and getattr(client, "authorization_grant_type", None) == "authorization-code"
        and getattr(client, "registration_source", None) == "manual"
    )


@contextmanager
def mcp_account_grant_guard(account_id):
    """Hold the account lock through the final grant check and write/sweep.

    Called only for the configured MCP resource. A SELECT FOR UPDATE alone is
    ineffective on SQLite. This no-op UPDATE is the transaction's first DB
    operation, acquiring SQLite's writer lock (or a row lock on PostgreSQL)
    before taking a snapshot or reading mutable grant state. It preserves the
    account's last_login and also serializes separate server processes.
    """
    database = router.db_for_write(get_access_token_model())
    with transaction.atomic(using=database):
        exists = get_user_model().objects.using(database).filter(pk=account_id).update(last_login=F("last_login"))
        yield bool(exists)
