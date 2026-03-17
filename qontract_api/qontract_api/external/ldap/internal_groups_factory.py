"""Factory for creating InternalGroupsWorkspaceClient instances."""

import hashlib

from qontract_utils.internal_groups_api import InternalGroupsApi

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.ldap.internal_groups_workspace_client import (
    InternalGroupsWorkspaceClient,
)
from qontract_api.external.ldap.schemas import LdapSecret
from qontract_api.secret_manager import SecretManager


def create_internal_groups_workspace_client(
    secret: LdapSecret,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> InternalGroupsWorkspaceClient:
    """Create InternalGroupsWorkspaceClient with caching.

    Args:
        secret: LdapSecret with OAuth2 connection details
        cache: Cache backend for distributed cache
        secret_manager: Secret backend for retrieving OAuth2 client secret
        settings: Application settings

    Returns:
        InternalGroupsWorkspaceClient instance with caching
    """
    client_secret = secret_manager.read(secret)

    api = InternalGroupsApi(
        base_url=secret.base_url,
        token_url=secret.token_url,
        client_id=secret.client_id,
        client_secret=client_secret,
    )

    # Use a hash of base_url + client_id as the cache key prefix for uniqueness
    prefix = hashlib.sha256(
        f"{secret.base_url}:{secret.client_id}".encode()
    ).hexdigest()[:16]

    return InternalGroupsWorkspaceClient(
        api=api,
        cache=cache,
        settings=settings,
        cache_key_prefix=prefix,
    )
