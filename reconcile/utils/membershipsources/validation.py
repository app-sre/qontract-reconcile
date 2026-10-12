from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from reconcile.utils.membershipsources.models import MembershipSourceEntry


class RoleWithMemberSources(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def member_sources(self) -> Iterable[MembershipSourceEntry] | None: ...


class CircularMembershipError(Exception):
    """A role's memberSources references a group also published by ldap-groups."""


def find_circular_memberships(
    roles: Iterable[RoleWithMemberSources],
    published_ldap_groups: Iterable[str],
) -> list[tuple[str, str]]:
    """Return (role_name, group) pairs forming a circular membership dependency.

    The ldap-groups integration pushes role membership TO Rover/LDAP groups
    (role.ldapGroup). An LDAP-provider memberSources entry pulls membership
    FROM an LDAP group. Without this check, a role could pull from a group
    that another role's ldapGroup publishes to, forming a cross-role cycle
    where reconciliation order decides which side's membership wins -
    silently overwriting one with the other on every run.

    Only memberSources entries whose provider discriminator is "ldap" are
    considered: an entry on any other provider (e.g. "app-interface", or a
    future one) reads from a different system entirely, so its `group`
    value is in a different namespace - a string collision with a published
    LDAP group name there is coincidental, not a real cycle.

    Args:
        roles: All roles to check (not just the ones with memberSources)
        published_ldap_groups: Group names published as ldapGroup targets,
            across all roles

    Returns:
        (role_name, group) pairs for every offending memberSources entry
    """
    published = {group.lower() for group in published_ldap_groups}
    if not published:
        return []
    return [
        (role.name, member_source.group)
        for role in roles
        for member_source in role.member_sources or []
        if member_source.provider.source.provider == "ldap"
        and member_source.group.lower() in published
    ]
