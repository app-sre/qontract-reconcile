"""FastAPI router for LDAP external API endpoints.

Provides cached access to LDAP user existence checks via direct FreeIPA LDAP
(see ADR-013: external calls through qontract-api).
"""

from __future__ import annotations

from fastapi import APIRouter

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.ldap.ldap_factory import (
    create_ldap_workspace_client,
)
from qontract_api.external.ldap.schemas import (
    LdapGithubUser,
    LdapGithubUsernamesRequest,
    LdapGithubUsernamesResponse,
    LdapUsersCheckRequest,
    LdapUsersCheckResponse,
)
from qontract_api.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/ldap",
    tags=["external"],
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


@router.post(
    "/github-usernames",
    operation_id="ldap-github-usernames",
)
def resolve_github_usernames(
    request: LdapGithubUsernamesRequest,
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    _user: UserDep,
) -> LdapGithubUsernamesResponse:
    """Resolve GitHub usernames to LDAP uids via the rhatSocialURL attribute.

    Maps each requested GitHub username to the app-interface org_username (LDAP
    uid) of the user whose rhatSocialURL points at that GitHub account. The
    full map is cached for performance; unresolved logins are omitted from the
    response.

    Args:
        request: GitHub usernames to resolve and the Vault secret reference
        cache: Cache dependency
        secret_manager: Secret manager dependency

    Returns:
        LdapGithubUsernamesResponse with resolved username -> org_username pairs
    """
    client = create_ldap_workspace_client(
        secret=request.secret,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    resolved = client.resolve_github_usernames(request.logins)

    logger.info(
        f"Resolved {len(resolved)}/{len(request.logins)} GitHub usernames via LDAP",
        requested=len(request.logins),
        resolved=len(resolved),
    )

    return LdapGithubUsernamesResponse(
        users=[
            LdapGithubUser(github_username=login, org_username=uid)
            for login, uid in resolved.items()
        ]
    )
