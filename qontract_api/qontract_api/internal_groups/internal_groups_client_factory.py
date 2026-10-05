"""Factory for InternalGroupsWorkspaceClient instances."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from qontract_utils.internal_groups_api import InternalGroupsApi

from qontract_api.internal_groups.internal_groups_workspace_client import (
    InternalGroupsWorkspaceClient,
)

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.internal_groups.domain import InternalGroupsConnectionSecret
    from qontract_api.secret_manager import SecretManager


def create_internal_groups_workspace_client(
    connection: InternalGroupsConnectionSecret,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> InternalGroupsWorkspaceClient:
    """Create InternalGroupsWorkspaceClient with optional GET caching."""
    credentials = secret_manager.read_all(connection)
    client_secret = credentials["client_secret"]

    def _build_api() -> InternalGroupsApi:
        return InternalGroupsApi(
            api_url=connection.api_url,
            issuer_url=connection.issuer_url,
            client_id=connection.client_id,
            client_secret=client_secret,
        )

    environment_key = hashlib.sha256(
        f"{connection.api_url}:{connection.client_id}".encode()
    ).hexdigest()

    return InternalGroupsWorkspaceClient(
        api_factory=_build_api,
        cache=cache,
        settings=settings,
        environment_key=environment_key,
    )
