"""API schemas for LDAP external integration."""

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class LdapSecret(Secret, frozen=True):
    """Extended secret reference for OAuth2-protected LDAP group APIs.

    Inherits standard secret fields from Secret (for OAuth2 client_secret lookup)
    and adds OAuth2 connection details.

    Attributes:
        base_url: Base URL of the internal groups API
        token_url: OAuth2 token endpoint URL
        client_id: OAuth2 client ID (plain text)
        (inherited) secret_manager_url, path, field, version: OAuth2 client secret ref
    """

    base_url: str = Field(..., description="Base URL of the internal groups API")
    token_url: str = Field(..., description="OAuth2 token endpoint URL")
    client_id: str = Field(..., description="OAuth2 client ID")


class LdapGroupMember(BaseModel, frozen=True):
    """A member of an LDAP group.

    Attributes:
        id: Member identifier (username or email)
    """

    id: str = Field(..., description="Member identifier (username or email)")


class LdapGroupMembersResponse(BaseModel, frozen=True):
    """Response model for LDAP group members endpoint.

    Attributes:
        members: List of LDAP group members
    """

    members: list[LdapGroupMember] = Field(
        default_factory=list,
        description="List of LDAP group members",
    )


# --- Direct LDAP (FreeIPA) schemas ---


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
