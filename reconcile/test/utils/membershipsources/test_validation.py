from __future__ import annotations

import pytest

from reconcile.test.utils.membershipsources.fixtures import (
    build_ldap_membership_source,
    build_role,
)
from reconcile.utils.membershipsources.validation import find_circular_memberships


def test_find_circular_memberships_detects_conflict() -> None:
    roles = [
        build_role(
            name="role-a",
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-x")
            ],
        ),
    ]

    conflicts = find_circular_memberships(roles, published_ldap_groups={"team-x"})

    assert conflicts == [("role-a", "team-x")]


@pytest.mark.parametrize(
    ("source_group", "published_group"),
    [("TEAM-X", "team-x"), ("team-x", "TEAM-X"), ("Team-X", "tEAM-x")],
)
def test_find_circular_memberships_matches_case_insensitively(
    source_group: str, published_group: str
) -> None:
    roles = [
        build_role(
            name="role-a",
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group=source_group)
            ],
        )
    ]

    assert find_circular_memberships(roles, {published_group}) == [
        ("role-a", source_group)
    ]


def test_find_circular_memberships_no_conflict_for_disjoint_groups() -> None:
    roles = [
        build_role(
            name="role-a",
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-x")
            ],
        ),
    ]

    assert find_circular_memberships(roles, published_ldap_groups={"team-y"}) == []


def test_find_circular_memberships_skips_validation_when_no_published_groups() -> None:
    roles = [
        build_role(
            name="role-a",
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-x")
            ],
        ),
    ]

    assert find_circular_memberships(roles, published_ldap_groups=set()) == []


def test_find_circular_memberships_ignores_roles_without_member_sources() -> None:
    roles = [build_role(name="role-a", users=["alice"])]

    assert find_circular_memberships(roles, published_ldap_groups={"team-x"}) == []


def test_find_circular_memberships_detects_multiple_conflicts() -> None:
    roles = [
        build_role(
            name="role-a",
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-x")
            ],
        ),
        build_role(
            name="role-b",
            member_sources=[
                build_ldap_membership_source(name="corp-ldap", group="team-y")
            ],
        ),
    ]

    conflicts = find_circular_memberships(
        roles, published_ldap_groups={"team-x", "team-y"}
    )

    assert sorted(conflicts) == [("role-a", "team-x"), ("role-b", "team-y")]
