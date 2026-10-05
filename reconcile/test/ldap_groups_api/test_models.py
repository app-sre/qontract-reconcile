"""Tests for ldap-groups-api desired-state helpers."""

from qontract_utils.internal_groups_api.models import Group

from reconcile.ldap_groups_api.models import validate_no_circular_memberships


def test_validate_no_circular_memberships_empty() -> None:
    validate_no_circular_memberships([], [])


def test_validate_no_circular_memberships_no_conflict() -> None:
    group = Group(
        name="g1",
        description="d",
        contact_list="a@b.com",
        owners=[],
        display_name="g1",
    )
    validate_no_circular_memberships([], [group])
