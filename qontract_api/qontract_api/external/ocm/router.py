"""FastAPI router for OCM external API endpoints.

Provides cached, label-based cluster discovery against OCM (see ADR-013: external
calls through qontract-api). Deliberately domain-agnostic: it has no notion of
"rhidp" or any other consumer - callers pass their own label_key_prefix and
interpret the returned labels themselves.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.ocm.ocm_client_factory import create_ocm_workspace_client
from qontract_api.external.ocm.schemas import (
    OcmClusterInfo,
    OcmClusterQueryParams,
    OcmClustersResponse,
)
from qontract_api.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/ocm",
    tags=["external"],
)


@router.get(
    "/clusters",
    operation_id="ocm-clusters",
)
def get_clusters(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    _user: UserDep,
    params: Annotated[
        OcmClusterQueryParams,
        Query(description="OCM cluster discovery query parameters"),
    ],
) -> OcmClustersResponse:
    """Discover OCM clusters with subscription/organization labels matching a prefix.

    Returns raw cluster info plus a flat dict of matching labels, merged with
    subscription-level labels winning over organization-level labels on key
    collisions. Label *interpretation* is left entirely to the caller. Results
    are cached (TTL configured in settings).
    """
    client = create_ocm_workspace_client(
        params=params,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    # Treat an omitted or empty org_ids as "no filter" - HTTP query strings can't
    # cleanly distinguish "absent" from "explicitly empty".
    org_ids = set(params.org_ids) if params.org_ids else None
    clusters = client.get_clusters(
        label_key_prefix=params.label_key_prefix, org_ids=org_ids
    )

    logger.info(
        f"Found {len(clusters)} clusters matching label prefix {params.label_key_prefix}",
        label_key_prefix=params.label_key_prefix,
        cluster_count=len(clusters),
    )

    return OcmClustersResponse(
        clusters=[
            OcmClusterInfo(
                id=c.id,
                name=c.name,
                organization_id=c.organization_id,
                console_url=c.console_url,
                external_auth_enabled=c.external_auth_enabled,
                labels=c.labels,
            )
            for c in clusters
        ]
    )
