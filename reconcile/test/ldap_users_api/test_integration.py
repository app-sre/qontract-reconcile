"""Tests for LDAP users API integration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest
from qontract_api_client.models.file_sync_delete import FileSyncDelete
from qontract_api_client.models.file_sync_response import FileSyncResponse
from qontract_api_client.models.file_sync_status import FileSyncStatus
from qontract_api_client.models.ldap_user_status import LdapUserStatus
from qontract_api_client.models.ldap_users_check_response import (
    LdapUsersCheckResponse,
)
from qontract_utils.vcs import Provider

from reconcile.gql_definitions.common.users_with_paths import (
    AppInterfaceSqlQueryV1,
    AWSAccountV1,
    CredentialsRequestV1,
    GabiInstanceV1,
    ScheduleV1,
    SRECheckpointV1,
    UserV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.ldap_users_api.integration import (
    LdapUsersApiIntegration,
    LdapUsersApiIntegrationParams,
    _find_vcs_secret,
    transform_users_with_paths,
)
from reconcile.ldap_users_api.models import PathType
from reconcile.typed_queries.vcs import Vcs


def test_transform_users_with_paths() -> None:
    """Test transform_users_with_paths with all 7 path types."""
    user = UserV1(
        path="/path/to/user.yml",
        org_username="testuser",
        requests=[CredentialsRequestV1(path="/path/to/request1.yml")],
        queries=[AppInterfaceSqlQueryV1(path="/path/to/query1.yml")],
        gabi_instances=[GabiInstanceV1(path="/path/to/gabi1.yml")],
        aws_accounts=[AWSAccountV1(path="/path/to/aws1.yml")],
        schedules=[ScheduleV1(path="/path/to/schedule1.yml")],
        sre_checkpoints=[SRECheckpointV1(path="/path/to/checkpoint1.yml")],
    )

    result = transform_users_with_paths([user])

    assert len(result) == 1
    user_paths = result[0]
    assert user_paths.username == "testuser"
    assert len(user_paths.paths) == 7

    path_types = {p.type for p in user_paths.paths}
    assert path_types == {
        PathType.USER,
        PathType.REQUEST,
        PathType.QUERY,
        PathType.GABI,
        PathType.AWS_ACCOUNTS,
        PathType.SCHEDULE,
        PathType.SRE_CHECKPOINT,
    }

    path_dict = {p.type: p.path for p in user_paths.paths}
    assert path_dict[PathType.USER] == "data/path/to/user.yml"
    assert path_dict[PathType.REQUEST] == "data/path/to/request1.yml"
    assert path_dict[PathType.QUERY] == "data/path/to/query1.yml"
    assert path_dict[PathType.GABI] == "data/path/to/gabi1.yml"
    assert path_dict[PathType.AWS_ACCOUNTS] == "data/path/to/aws1.yml"
    assert path_dict[PathType.SCHEDULE] == "data/path/to/schedule1.yml"
    assert path_dict[PathType.SRE_CHECKPOINT] == "data/path/to/checkpoint1.yml"


def test_transform_users_with_paths_none_optionals() -> None:
    """Test transform_users_with_paths with None optional fields."""
    user = UserV1(
        path="/path/to/user.yml",
        org_username="testuser",
        requests=None,
        queries=None,
        gabi_instances=None,
        aws_accounts=None,
        schedules=None,
        sre_checkpoints=None,
    )

    result = transform_users_with_paths([user])

    assert len(result) == 1
    user_paths = result[0]
    assert user_paths.username == "testuser"
    assert len(user_paths.paths) == 1

    assert user_paths.paths[0].type == PathType.USER
    assert user_paths.paths[0].path == "data/path/to/user.yml"


def test_transform_users_with_paths_multiple_items() -> None:
    """Test transform_users_with_paths with multiple requests/queries/etc."""
    user = UserV1(
        path="/path/to/user.yml",
        org_username="testuser",
        requests=[
            CredentialsRequestV1(path="/path/to/request1.yml"),
            CredentialsRequestV1(path="/path/to/request2.yml"),
        ],
        queries=[
            AppInterfaceSqlQueryV1(path="/path/to/query1.yml"),
            AppInterfaceSqlQueryV1(path="/path/to/query2.yml"),
        ],
        gabi_instances=None,
        aws_accounts=[AWSAccountV1(path="/path/to/aws1.yml")],
        schedules=None,
        sre_checkpoints=None,
    )

    result = transform_users_with_paths([user])

    assert len(result) == 1
    user_paths = result[0]
    assert user_paths.username == "testuser"
    # 1 USER + 2 REQUEST + 2 QUERY + 1 AWS_ACCOUNTS = 6 paths
    assert len(user_paths.paths) == 6

    request_paths = [p for p in user_paths.paths if p.type == PathType.REQUEST]
    query_paths = [p for p in user_paths.paths if p.type == PathType.QUERY]
    aws_paths = [p for p in user_paths.paths if p.type == PathType.AWS_ACCOUNTS]

    assert len(request_paths) == 2
    assert len(query_paths) == 2
    assert len(aws_paths) == 1


# --- _find_vcs_secret ---


def _make_vcs(name: str, url: str) -> Vcs:
    return Vcs(
        name=name,
        url=url,
        token=VaultSecret(
            path="secret/vcs/token", field="token", version=1, format=None
        ),
        provider=Provider.GITLAB,
    )


def test_find_vcs_secret_found() -> None:
    """Test _find_vcs_secret finds matching VCS instance by URL prefix."""
    vcs_instances = [
        _make_vcs("gitlab-cee", "https://gitlab.cee.redhat.com"),
        _make_vcs("github", "https://github.com"),
    ]

    secret = _find_vcs_secret(
        "https://vault.example.com",
        vcs_instances,
        "https://gitlab.cee.redhat.com/service/app-interface",
    )

    assert secret.secret_manager_url == "https://vault.example.com"
    assert secret.path == "secret/vcs/token"
    assert secret.field == "token"


def test_find_vcs_secret_not_found() -> None:
    """Test _find_vcs_secret raises ValueError when no match."""
    vcs_instances = [
        _make_vcs("github", "https://github.com"),
    ]

    with pytest.raises(ValueError, match="No VCS instance found"):
        _find_vcs_secret(
            "https://vault.example.com",
            vcs_instances,
            "https://gitlab.cee.redhat.com/service/app-interface",
        )


# --- async_run tests ---

_MOD = "reconcile.ldap_users_api.integration"
_APP_REPO = "https://gitlab.example.com/service/app-interface"
_INFRA_REPO = "https://gitlab.example.com/app-sre/infra"


def _make_user(username: str) -> UserV1:
    return UserV1(
        path=f"/access/users/{username}.yml",
        org_username=username,
        requests=None,
        queries=None,
        gabi_instances=None,
        aws_accounts=None,
        schedules=None,
        sre_checkpoints=None,
    )


def _ldap_settings() -> MagicMock:
    settings = MagicMock()
    settings.server_url = "ldap://freeipa.example.com"
    settings.base_dn = "dc=example,dc=com"
    settings.credentials = VaultSecret(
        path="secret/ldap", field="all", version=1, format=None
    )
    return settings


def _ldap_response(
    users: dict[str, bool],
) -> LdapUsersCheckResponse:
    return LdapUsersCheckResponse(
        users=[
            LdapUserStatus(username=name, exists=exists)
            for name, exists in users.items()
        ]
    )


def _vcs_instances() -> list[Vcs]:
    return [
        _make_vcs("gitlab", "https://gitlab.example.com"),
    ]


@pytest.fixture
def integration() -> Generator[LdapUsersApiIntegration, None, None]:
    """Create integration instance with mocked base class properties."""
    inst = LdapUsersApiIntegration(
        LdapUsersApiIntegrationParams(
            app_interface_repo_url=_APP_REPO,
            infra_repo_url=_INFRA_REPO,
            infra_paths=["ansible/hosts/group_vars/all"],
            labels=["ldap-users"],
        )
    )
    with (
        patch.object(
            type(inst),
            "qontract_api_client",
            new_callable=lambda: property(lambda self: MagicMock()),
        ),
        patch.object(
            type(inst),
            "secret_manager_url",
            new_callable=lambda: property(lambda self: "https://vault.example.com"),
        ),
    ):
        yield inst


@pytest.mark.asyncio
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.get_users_with_paths")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.check_ldap_users", new_callable=AsyncMock)
async def test_async_run_safety_check_aborts_when_ldap_empty(
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_users: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    integration: LdapUsersApiIntegration,
) -> None:
    """If LDAP returns no existing users, abort with RuntimeError."""
    mock_users.return_value = [_make_user("alice"), _make_user("bob")]
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": False, "bob": False})

    with pytest.raises(RuntimeError, match="LDAP returned empty result set"):
        await integration.async_run(dry_run=False)


@pytest.mark.asyncio
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.get_users_with_paths")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.check_ldap_users", new_callable=AsyncMock)
async def test_async_run_no_users_to_delete(
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_users: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    integration: LdapUsersApiIntegration,
) -> None:
    """If all users exist in LDAP, do nothing."""
    mock_users.return_value = [_make_user("alice")]
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": True})

    await integration.async_run(dry_run=False)


@pytest.mark.asyncio
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.build_infra_file_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.build_app_interface_file_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.get_users_with_paths")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.check_ldap_users", new_callable=AsyncMock)
async def test_async_run_dry_run_does_not_call_file_sync(
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_users: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_build_app: AsyncMock,
    mock_build_infra: AsyncMock,
    mock_file_sync: AsyncMock,
    integration: LdapUsersApiIntegration,
) -> None:
    """In dry-run mode, file-sync endpoint is never called."""
    mock_users.return_value = [_make_user("alice")]
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": False, "bob": True})
    mock_build_app.return_value = [
        FileSyncDelete(path="data/access/users/alice.yml", commit_message="del"),
    ]
    mock_build_infra.return_value = []

    await integration.async_run(dry_run=True)

    mock_file_sync.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.build_infra_file_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.build_app_interface_file_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.get_users_with_paths")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.check_ldap_users", new_callable=AsyncMock)
async def test_async_run_calls_file_sync_for_deleted_user(
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_users: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_build_app: AsyncMock,
    mock_build_infra: AsyncMock,
    mock_file_sync: AsyncMock,
    integration: LdapUsersApiIntegration,
) -> None:
    """Non-dry-run calls file-sync for users not in LDAP."""
    mock_users.return_value = [_make_user("alice"), _make_user("bob")]
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": False, "bob": True})
    mock_build_app.return_value = [
        FileSyncDelete(path="data/access/users/alice.yml", commit_message="del"),
    ]
    mock_build_infra.return_value = []
    mock_file_sync.return_value = FileSyncResponse(
        status=FileSyncStatus.MR_CREATED,
        mr_url="https://gitlab.example.com/mr/1",
    )

    await integration.async_run(dry_run=False)

    mock_file_sync.assert_called_once()
    call_body = mock_file_sync.call_args.kwargs["body"]
    assert call_body.repo_url == _APP_REPO
    assert call_body.title == "[create_delete_user_mr] delete user alice"
    assert len(call_body.file_operations) == 1


@pytest.mark.asyncio
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.get_users_with_paths")
@patch(f"{_MOD}.gql")
async def test_async_run_no_usernames_returns_early(
    mock_gql: MagicMock,
    mock_users: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    integration: LdapUsersApiIntegration,
) -> None:
    """If GraphQL returns no users, return immediately."""
    mock_users.return_value = []
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()

    await integration.async_run(dry_run=False)


@pytest.mark.asyncio
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.get_users_with_paths")
@patch(f"{_MOD}.gql")
async def test_async_run_missing_ldap_credentials(
    mock_gql: MagicMock,
    mock_users: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    integration: LdapUsersApiIntegration,
) -> None:
    """If LDAP credentials are missing, raise RuntimeError."""
    mock_users.return_value = [_make_user("alice")]
    settings = MagicMock()
    settings.credentials = None
    mock_settings.return_value = settings
    mock_vcs.return_value = _vcs_instances()

    with pytest.raises(RuntimeError, match="LDAP credentials not found"):
        await integration.async_run(dry_run=False)
