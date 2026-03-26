"""FastAPI router for LDAP external API endpoints.

Provides cached access to LDAP group memberships via an OAuth2-protected
internal groups proxy API (see ADR-013: external calls through qontract-api).
"""

from typing import Annotated

from fastapi import APIRouter, Query

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep
from qontract_api.external.ldap.internal_groups_factory import (
    create_internal_groups_workspace_client,
)
from qontract_api.external.ldap.schemas import (
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapSecret,
)
from qontract_api.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/ldap",
    tags=["external"],
)


@router.get(
    "/groups/{group_name}/members",
    operation_id="ldap-group-members",
)
def get_group_members(
    group_name: str,
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    secret: Annotated[
        LdapSecret,
        Query(description="LDAP OAuth2 secret reference"),
    ],
) -> LdapGroupMembersResponse:
    """Get members of an LDAP group.

    Fetches members from the internal groups proxy API using OAuth2
    client-credentials authentication. Results are cached for performance.

    Args:
        group_name: LDAP group name
        cache: Cache dependency
        secret_manager: Secret manager dependency
        secret: LdapSecret with OAuth2 connection details and client_secret reference

    Returns:
        LdapGroupMembersResponse with list of group members

    Raises:
        HTTPException:
            - 500 Internal Server Error: If the internal groups API call fails
    """
    client = create_internal_groups_workspace_client(
        secret=secret,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    group = client.get_group(group_name)

    logger.info(
        f"Found {len(group.members)} members in group {group_name}",
        group_name=group_name,
        member_count=len(group.members),
    )

    return LdapGroupMembersResponse(
        members=[LdapGroupMember(id=m.id) for m in group.members]
    )
