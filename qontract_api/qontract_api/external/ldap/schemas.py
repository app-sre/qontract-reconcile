"""API schemas for LDAP external integration."""

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class LdapDirectSecret(Secret, frozen=True):
    """VaultSecret reference for FreeIPA direct LDAP access.

    The referenced Vault path must contain bind_dn and bind_password fields.
    No plain credentials are transmitted via API -- only Vault path references.

    Attributes:
        server_url: LDAP server URL (e.g., "ldap://freeipa.example.com")
        base_dn: Base DN for LDAP searches (e.g., "dc=example,dc=com")
        (inherited) secret_manager_url, path, field, version: Vault secret ref
    """

    server_url: str = Field(..., description="LDAP server URL")
    base_dn: str = Field(..., description="Base DN for LDAP searches")


class LdapUsersCheckRequest(BaseModel, frozen=True):
    """Request to check which usernames exist in LDAP."""

    usernames: list[str] = Field(..., description="Usernames to check")
    secret: LdapDirectSecret = Field(
        ..., description="Vault secret reference for LDAP credentials"
    )


class LdapUserStatus(BaseModel, frozen=True):
    """Existence status of a single LDAP user."""

    username: str = Field(..., description="Username")
    exists: bool = Field(..., description="Whether the user exists in LDAP")


class LdapUsersCheckResponse(BaseModel, frozen=True):
    """Response with existence status per username."""

    users: list[LdapUserStatus] = Field(
        default_factory=list,
        description="Existence status for each requested username",
    )
