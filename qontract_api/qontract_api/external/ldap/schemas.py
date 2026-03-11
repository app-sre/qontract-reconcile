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
