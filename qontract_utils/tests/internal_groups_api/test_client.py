from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from qontract_utils.internal_groups_api.api import InternalGroupsApi, NotFoundError
from qontract_utils.internal_groups_api.client import InternalGroupsClient
from qontract_utils.internal_groups_api.models import Group

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer


def test_internal_groups_api_create_group(
    httpserver: HTTPServer, internal_groups_api: InternalGroupsApi
) -> None:
    result = internal_groups_api.create_group(data={"fake": "fake"})
    assert result["name"] == "test-group"
    assert httpserver.log[0][0].json == {"fake": "fake"}


def test_internal_groups_api_delete_group(
    internal_groups_api: InternalGroupsApi,
    group_name: str,
) -> None:
    internal_groups_api.delete_group(name=group_name)


def test_internal_groups_api_delete_unknown_group(
    internal_groups_api: InternalGroupsApi,
    non_existent_group_name: str,
) -> None:
    with pytest.raises(NotFoundError):
        internal_groups_api.delete_group(name=non_existent_group_name)


def test_internal_groups_api_update_group(
    httpserver: HTTPServer,
    internal_groups_api: InternalGroupsApi,
    group_name: str,
) -> None:
    internal_groups_api.update_group(name=group_name, data={"fake": "fake"})
    assert httpserver.log[0][0].json == {"fake": "fake"}


def test_internal_groups_api_get_group(
    httpserver: HTTPServer,
    internal_groups_api: InternalGroupsApi,
    group_name: str,
) -> None:
    internal_groups_api.group(name=group_name)
    assert httpserver.log[0][0].headers.get("content-type") == "application/json"


def test_internal_groups_api_get_group_not_found(
    internal_groups_api: InternalGroupsApi, non_existent_group_name: str
) -> None:
    with pytest.raises(NotFoundError):
        internal_groups_api.group(name=non_existent_group_name)


def test_internal_groups_client_create_group(
    internal_groups_client: InternalGroupsClient,
    group_name: str,
) -> None:
    group = Group(
        name=group_name,
        description="test group",
        contact_list="email@example.org",
        owners=[],
        display_name="display",
    )
    assert internal_groups_client.create_group(group).name == group_name


def test_internal_groups_client_get_group(
    internal_groups_client: InternalGroupsClient,
    group_name: str,
) -> None:
    group = internal_groups_client.group(group_name)
    assert group.name == group_name


def test_internal_groups_client_get_unknown_group(
    internal_groups_client: InternalGroupsClient, non_existent_group_name: str
) -> None:
    with pytest.raises(NotFoundError):
        internal_groups_client.group(non_existent_group_name)


def test_internal_groups_client_update_group(
    internal_groups_client: InternalGroupsClient,
    group_name: str,
) -> None:
    group = internal_groups_client.group(group_name)
    assert internal_groups_client.update_group(group).name == group_name


def test_internal_groups_client_delete_group(
    internal_groups_client: InternalGroupsClient,
    group_name: str,
) -> None:
    internal_groups_client.delete_group(group_name)
