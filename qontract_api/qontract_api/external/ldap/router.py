"""FastAPI router for LDAP external API endpoints.

Provides cached access to:
- LDAP group memberships via OAuth2-protected internal groups proxy API
- LDAP user existence checks via direct FreeIPA LDAP
(see ADR-013: external calls through qontract-api).
"""

from typing import Annotated

from fastapi import APIRouter, Query

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.ldap.internal_groups_factory import (
    create_internal_groups_workspace_client,
)
from qontract_api.external.ldap.ldap_factory import (
    create_ldap_workspace_client,
)
from qontract_api.external.ldap.schemas import (
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapSecret,
    LdapUsersCheckRequest,
    LdapUsersCheckResponse,
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
    _user: UserDep,
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


@router.post(
    "/users/check",
    operation_id="ldap-users-check",
)
def check_users_exist(
    request: LdapUsersCheckRequest,
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    _user: UserDep,
) -> LdapUsersCheckResponse:
    """Check which usernames exist in LDAP (cached, FreeIPA-authenticated).

    Queries LDAP directly using FreeIPA service account credentials
    resolved from Vault. Results are cached for performance.

    Args:
        request: Request with usernames to check and Vault secret reference
        cache: Cache dependency
        secret_manager: Secret manager dependency

    Returns:
        LdapUsersCheckResponse with existence status per username
    """
    client = create_ldap_workspace_client(
        secret=request.secret,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    result = client.check_users_exist(request.usernames)

    logger.info(
        f"Checked {len(request.usernames)} usernames in LDAP",
        total=len(request.usernames),
        existing=sum(1 for u in result if u.exists),
    )

    return LdapUsersCheckResponse(users=result)
