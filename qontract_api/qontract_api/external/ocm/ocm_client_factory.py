"""Factory for creating OcmWorkspaceClient instances.

Service layer should use OcmWorkspaceClient, not OcmApi directly.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from qontract_utils.ocm_api import OcmApi

from qontract_api.external.ocm.ocm_workspace_client import OcmWorkspaceClient

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.external.ocm.schemas import OcmClusterQueryParams
    from qontract_api.secret_manager import SecretManager


def create_ocm_workspace_client(
    params: OcmClusterQueryParams,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> OcmWorkspaceClient:
    """Create OcmWorkspaceClient with caching.

    The Vault read for access_token_client_secret and the OAuth2 token exchange
    with Red Hat SSO that OcmApi.__init__ performs eagerly are both deferred behind
    a factory closure, so a cache hit in OcmWorkspaceClient never triggers either.

    Args:
        params: OCM connection + cluster discovery query parameters
        cache: Cache backend for distributed cache
        secret_manager: Secret backend for retrieving the OCM client secret
        settings: Application settings with OCM configuration

    Returns:
        OcmWorkspaceClient instance with caching
    """

    def _build_ocm_api() -> OcmApi:
        access_token_client_secret = secret_manager.read(params)
        return OcmApi(
            url=params.ocm_url,
            access_token_url=params.access_token_url,
            access_token_client_id=params.access_token_client_id,
            access_token_client_secret=access_token_client_secret,
            timeout=settings.ocm.api_timeout,
            max_retries=settings.ocm.api_max_retries,
        )

    # Stable, non-secret identity for this OCM environment + calling client, used
    # as a cache-key component (mirrors ldap_factory's hash-based cache prefix).
    environment_key = hashlib.sha256(
        f"{params.ocm_url}:{params.access_token_client_id}".encode()
    ).hexdigest()

    return OcmWorkspaceClient(
        ocm_api_factory=_build_ocm_api,
        cache=cache,
        settings=settings,
        environment_key=environment_key,
    )
