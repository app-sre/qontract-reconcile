"""Pydantic models for LDAP API responses."""

from pydantic import BaseModel


class LdapUser(BaseModel, frozen=True):
    """An LDAP user returned by get_users.

    Attributes:
        username: LDAP uid attribute value
    """

    username: str


class LdapGroup(BaseModel, frozen=True):
    """An LDAP group returned by get_group_members.

    Attributes:
        dn: Full distinguished name of the group
        members: Set of member LDAP users
    """

    cn: str
    dn: str
    members: frozenset[LdapUser]
