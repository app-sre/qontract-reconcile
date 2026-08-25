"""Unit tests for QuayWorkspaceClient cache and invalidation."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.quay_api import QuayApi
from qontract_utils.quay_api.models import (
    RobotAccount,
    RobotAccountPermission,
    RobotAccountRepository,
)

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.quay.quay_workspace_client import (
    CachedRobotAccounts,
    QuayWorkspaceClient,
)


@pytest.fixture
def mock_api() -> MagicMock:
    return MagicMock(spec=QuayApi)


@pytest.fixture
def mock_cache() -> MagicMock:
    mock = MagicMock(spec=CacheBackend)
    mock.get_obj.return_value = None
    mock.lock.return_value.__enter__ = MagicMock()
    mock.lock.return_value.__exit__ = MagicMock(return_value=False)
    return mock


@pytest.fixture
def client(mock_api: MagicMock, mock_cache: MagicMock) -> QuayWorkspaceClient:
    return QuayWorkspaceClient(
        quay_api=mock_api,
        instance_name="quay-io",
        organization="test-org",
        cache=mock_cache,
        settings=Settings(),
    )


def test_list_robot_accounts_cache_miss(
    client: QuayWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    robots = [RobotAccount(name="ci-bot")]
    mock_api.list_robot_accounts.return_value = robots

    result = client.list_robot_accounts()

    assert result == robots
    mock_api.list_robot_accounts.assert_called_once()
    mock_cache.set_obj.assert_called_once()
    assert mock_cache.set_obj.call_args.args[0] == "quay:quay-io:test-org:robots"


def test_list_robot_accounts_cache_hit(
    client: QuayWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    robots = [RobotAccount(name="ci-bot")]
    mock_cache.get_obj.return_value = CachedRobotAccounts(items=robots)

    result = client.list_robot_accounts()

    assert result == robots
    mock_api.list_robot_accounts.assert_not_called()


def test_create_robot_invalidates_list_cache(
    client: QuayWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    client.create_robot_account("ci-bot", "CI")
    mock_api.create_robot_account.assert_called_once_with("ci-bot", "CI")
    mock_cache.delete.assert_called_once_with("quay:quay-io:test-org:robots")


def test_delete_robot_invalidates_list_and_permissions(
    client: QuayWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.delete_robot_account("ci-bot")
    deleted = {call.args[0] for call in mock_cache.delete.call_args_list}
    assert "quay:quay-io:test-org:robots" in deleted
    assert "quay:quay-io:test-org:robot:ci-bot:permissions" in deleted


def test_add_robot_to_team_prefixes_org(
    client: QuayWorkspaceClient, mock_api: MagicMock
) -> None:
    client.add_robot_to_team("ci-bot", "sre")
    mock_api.add_user_to_team.assert_called_once_with("test-org+ci-bot", "sre")


def test_set_repo_permission_invalidates_permissions_cache(
    client: QuayWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.set_repo_robot_account_permissions("images", "ci-bot", "write")
    mock_cache.delete.assert_called_once_with(
        "quay:quay-io:test-org:robot:ci-bot:permissions"
    )


def test_get_robot_account_permissions_cache_miss(
    client: QuayWorkspaceClient, mock_api: MagicMock
) -> None:
    perms = [
        RobotAccountPermission(
            repository=RobotAccountRepository(name="images"), role="read"
        )
    ]
    mock_api.get_robot_account_permissions.return_value = perms

    result = client.get_robot_account_permissions("ci-bot")

    assert result == perms
    mock_api.get_robot_account_permissions.assert_called_once_with("ci-bot")


def test_close_delegates_to_api(
    client: QuayWorkspaceClient, mock_api: MagicMock
) -> None:
    client.close()
    mock_api.close.assert_called_once()
