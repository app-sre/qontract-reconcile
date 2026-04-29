"""FastAPI router for LDAP external API endpoints.

Provides cached access to LDAP user existence checks via direct FreeIPA LDAP
(see ADR-013: external calls through qontract-api).
"""

from fastapi import APIRouter

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.ldap.ldap_factory import (
    create_ldap_workspace_client,
)
from qontract_api.external.ldap.schemas import (
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
