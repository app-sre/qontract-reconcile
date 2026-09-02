"""Factory for creating QuayWorkspaceClient instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.quay_api import QuayApi

from qontract_api.quay.quay_workspace_client import QuayWorkspaceClient

if TYPE_CHECKING:
    from qontract_utils.secret_reader import Secret

    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.secret_manager import SecretManager


def create_quay_workspace_client(
    secret: Secret,
    org_name: str,
    base_url: str,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> QuayWorkspaceClient:
    """Create a QuayWorkspaceClient with credentials resolved from the secret backend.

    Args:
        secret: Secret reference for the Quay API token
        org_name: Quay organization name
        base_url: Quay instance base URL (e.g. https://quay.io)
        cache: Cache backend for distributed caching and locking
        secret_manager: Secret backend for resolving the token
        settings: Application settings

    Returns:
        QuayWorkspaceClient instance with caching layer
    """
    token = secret_manager.read(secret)

    quay_api = QuayApi(org=org_name, token=token, base_url=base_url)

    return QuayWorkspaceClient(
        quay_api=quay_api,
        base_url=base_url,
        cache=cache,
        settings=settings,
    )
