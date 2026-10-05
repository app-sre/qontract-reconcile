"""Tests for ldap-groups-api desired-state helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from qontract_utils.internal_groups_api.models import Entity, EntityType, Group

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.ldap_groups_api.models import (
    get_desired_groups_for_aws_roles,
    get_desired_groups_for_roles,
    get_integration_settings,
    get_roles,
    validate_no_circular_memberships,
)
from reconcile.utils.aws_helper import unique_sso_aws_accounts_for_ldap_groups
from reconcile.utils.exceptions import AppInterfaceLdapGroupsSettingsError
from reconcile.utils.membershipsources.validation import CircularMembershipError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from reconcile.test.fixtures import Fixtures


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


@dataclass
class _Disable:
    integrations: list[str]


@dataclass
class _AwsAccount:
    name: str
    uid: str
    sso: bool = True
    disable: _Disable | None = None


@pytest.mark.parametrize(
    "disabled_integrations",
    [["ldap-groups"], ["ldap-groups-api"]],
)
def test_unique_sso_aws_accounts_for_ldap_groups_honors_both_disable_names(
    disabled_integrations: list[str],
) -> None:
    account = _AwsAccount(
        name="account-1",
        uid="123",
        disable=_Disable(integrations=disabled_integrations),
    )
    assert unique_sso_aws_accounts_for_ldap_groups([account]) == []


def test_get_desired_groups_for_aws_roles_builds_group_names(
    fx: Fixtures,
    gql_class_factory: Callable[[type[RoleV1], Mapping[str, Any]], RoleV1],
) -> None:
    raw = fx.get_anymarkup("roles.yml")
    roles = [
        gql_class_factory(RoleV1, item)
        for item in raw["roles"]
        if item.get("name") == "ldap-and-aws-role"
    ]
    owner = Entity(type=EntityType.SERVICE_ACCOUNT, id="sa-1")
    groups = get_desired_groups_for_aws_roles(
        roles,
        default_owners=[owner],
        contact_list="a@b.com",
        aws_sso_namespace="rover-prefix",
    )
    assert groups[0].name == "rover-prefix-123456789-ldap-and-aws-role"


def test_get_desired_groups_for_roles(
    roles: list[RoleV1],
) -> None:
    owner = Entity(type=EntityType.SERVICE_ACCOUNT, id="sa-1")
    groups = get_desired_groups_for_roles(
        roles,
        default_owners=[owner],
        contact_list="email@example.org",
    )
    assert {g.name for g in groups} == {"ai-dev-test-group", "ai-dev-test-group-with-notes"}
    assert groups[1].owners == [owner] + groups[1].members


def test_get_roles_raises_on_duplicate_ldap_group(
    gql_class_factory: Callable[..., RoleV1],
) -> None:
    dup_role = {
        "name": "role-a",
        "ldapGroup": {"name": "same-name"},
        "users": [],
    }

    class _RolesData:
        roles = [
            gql_class_factory(RoleV1, dup_role),
            gql_class_factory(RoleV1, {**dup_role, "name": "role-b"}),
        ]

    with (
        patch(
            "reconcile.ldap_groups_api.models.roles_query",
            return_value=_RolesData(),
        ),
        pytest.raises(ValueError, match="Duplicate ldapGroup"),
    ):
        get_roles(lambda *args, **kwargs: None)


def test_get_integration_settings_success() -> None:
    class _LdapGroupsSettings:
        contact_list = "a@b.com"

    class _Settings:
        ldap_groups = _LdapGroupsSettings()

    class _Data:
        settings = [_Settings()]

    with patch(
        "reconcile.ldap_groups_api.models.settings_query",
        return_value=_Data(),
    ):
        settings = get_integration_settings(lambda *args, **kwargs: None)
    assert settings.contact_list == "a@b.com"


def test_get_integration_settings_missing_ldap_groups() -> None:
    class _Settings:
        ldap_groups = None

    class _Data:
        settings = [_Settings()]

    with (
        patch(
            "reconcile.ldap_groups_api.models.settings_query",
            return_value=_Data(),
        ),
        pytest.raises(AppInterfaceLdapGroupsSettingsError),
    ):
        get_integration_settings(lambda *args, **kwargs: None)


def test_validate_no_circular_memberships_raises(
    gql_class_factory: Callable[..., RoleV1],
) -> None:
    group = Group(
        name="published",
        description="d",
        contact_list="a@b.com",
        owners=[],
        display_name="published",
    )
    role = gql_class_factory(RoleV1, {"name": "r1", "users": []})
    with (
        patch(
            "reconcile.ldap_groups_api.models.find_circular_memberships",
            return_value=[("r1", "published")],
        ),
        pytest.raises(CircularMembershipError),
    ):
        validate_no_circular_memberships([role], [group])
