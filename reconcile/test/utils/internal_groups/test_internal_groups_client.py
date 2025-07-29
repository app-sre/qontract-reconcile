import pytest
from pytest_httpserver import HTTPServer

from reconcile.test.fixtures import Fixtures
from reconcile.utils.internal_groups.client import (
    InternalGroupsApi,
    InternalGroupsClient,
    NotFoundError,
)
from reconcile.utils.internal_groups.models import Group


def test_internal_groups_api_create_group(
    httpserver: HTTPServer, internal_groups_api: InternalGroupsApi, fx: Fixtures
) -> None:
    assert internal_groups_api.create_group(data={"fake": "fake"}) == fx.get_json(
        "v1/groups/post.json"
    )

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
    fx: Fixtures,
    group_name: str,
) -> None:
    assert internal_groups_api.update_group(
        name=group_name, data={"fake": "fake"}
    ) == fx.get_json(f"v1/groups/{group_name}/patch.json")

    assert httpserver.log[0][0].json == {"fake": "fake"}


def test_internal_groups_api_get_group(
    httpserver: HTTPServer,
    internal_groups_api: InternalGroupsApi,
    fx: Fixtures,
    group_name: str,
) -> None:
    assert internal_groups_api.group(name=group_name) == fx.get_json(
        f"v1/groups/{group_name}/get.json"
    )

    assert httpserver.log[0][0].headers.get("content-type") == "application/json"


def test_internal_groups_api_get_group_not_found(
    internal_groups_api: InternalGroupsApi, non_existent_group_name: str
) -> None:
    with pytest.raises(NotFoundError):
        internal_groups_api.group(name=non_existent_group_name)


def test_internal_groups_client_create_group(
    internal_groups_client: InternalGroupsClient,
    fx: Fixtures,
    group_name: str,
):
    group = Group(**fx.get_json(f"v1/groups/{group_name}/get.json"))
    assert internal_groups_client.create_group(group) == group


def test_internal_groups_client_get_group(
    internal_groups_client: InternalGroupsClient,
    fx: Fixtures,
    group_name: str,
):
    group = Group(**fx.get_json(f"v1/groups/{group_name}/get.json"))
    assert internal_groups_client.group(group_name) == group


def test_internal_groups_client_get_unknown_group(
    internal_groups_client: InternalGroupsClient, non_existent_group_name: str
):
    with pytest.raises(NotFoundError):
        internal_groups_client.group(non_existent_group_name)


def test_internal_groups_client_update_group(
    internal_groups_client: InternalGroupsClient,
    fx: Fixtures,
    group_name: str,
):
    group = Group(**fx.get_json(f"v1/groups/{group_name}/patch.json"))
    assert internal_groups_client.update_group(group) == group


def test_internal_groups_client_update_unknown_group(
    internal_groups_client: InternalGroupsClient,
    fx: Fixtures,
    group_name: str,
    non_existent_group_name: str,
):
    group = Group(**fx.get_json(f"v1/groups/{group_name}/get.json"))
    group.name = non_existent_group_name
    with pytest.raises(NotFoundError):
        internal_groups_client.update_group(group)


def test_internal_groups_client_delete_group(
    internal_groups_client: InternalGroupsClient,
    group_name: str,
):
    internal_groups_client.delete_group(group_name)


def test_internal_groups_client_delete_unknown_group(
    internal_groups_client: InternalGroupsClient, non_existent_group_name: str
):
    with pytest.raises(NotFoundError):
        internal_groups_client.delete_group(non_existent_group_name)
