"""Factory for creating LdapWorkspaceClient instances."""

import hashlib

from qontract_utils.ldap_api import LdapApi

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.ldap.ldap_workspace_client import LdapWorkspaceClient
from qontract_api.external.ldap.schemas import LdapDirectSecret
from qontract_api.secret_manager import SecretManager


def create_ldap_workspace_client(
    secret: LdapDirectSecret,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> LdapWorkspaceClient:
    """Create LdapWorkspaceClient with caching for direct LDAP (FreeIPA).

    Resolves bind_dn and bind_password from Vault via SecretManager.
    Creates Layer 1 LdapApi, wraps with Layer 2 caching.

    Args:
        secret: LdapDirectSecret with server_url, base_dn, and Vault reference
        cache: Cache backend for distributed cache
        secret_manager: Secret backend for retrieving LDAP credentials
        settings: Application settings

    Returns:
        LdapWorkspaceClient instance with caching
    """
    credentials = secret_manager.read_all(secret)
    bind_dn = credentials["bind_dn"]
    bind_password = credentials["bind_password"]

    api = LdapApi(
        server_url=secret.server_url,
        base_dn=secret.base_dn,
        bind_dn=bind_dn,
        bind_password=bind_password,
        start_tls=True,
    )

    prefix = hashlib.sha256(
        f"{secret.server_url}:{secret.base_dn}".encode()
    ).hexdigest()

    return LdapWorkspaceClient(
        api=api,
        cache=cache,
        settings=settings,
        cache_key_prefix=prefix,
    )
