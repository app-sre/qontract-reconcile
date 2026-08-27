"""Unit tests for QuayRobotAccountsService."""

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
from qontract_api.integrations.quay_robot_accounts.domain import (
    QuayOrgDesiredState,
    QuayRobotDesiredState,
    QuayRobotRepository,
)
from qontract_api.integrations.quay_robot_accounts.schemas import (
    QuayRobotActionAddTeam,
    QuayRobotActionCreate,
    QuayRobotActionDelete,
    QuayRobotActionRemoveRepoPermission,
    QuayRobotActionRemoveTeam,
    QuayRobotActionSetRepoPermission,
)
from qontract_api.integrations.quay_robot_accounts.service import (
    QuayRobotAccountsService,
)
from qontract_api.models import Secret, TaskStatus
from qontract_api.quay import QuayWorkspaceClient
from qontract_api.quay.quay_workspace_client import CachedRobotAccounts


@pytest.fixture
def mock_settings() -> Settings:
    from qontract_api.config import SecretSettings, VaultSettings

    return Settings(
        secrets=SecretSettings(
            providers=[VaultSettings(url="https://vault.example.com")],
            default_provider_url="https://vault.example.com",
        ),
    )


@pytest.fixture
def test_token() -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/quay/token",
        field="token",
    )


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = "quay-token"
    return mock


@pytest.fixture
def mock_quay_client() -> MagicMock:
    mock = MagicMock(spec=QuayWorkspaceClient)
    mock.list_robot_accounts.return_value = []
    mock.get_robot_account_permissions.return_value = []
    return mock


@pytest.fixture
def mock_quay_client_factory(mock_quay_client: MagicMock) -> MagicMock:
    mock = MagicMock()
    mock.create_workspace_client.return_value = mock_quay_client
    return mock


@pytest.fixture
def service(
    mock_quay_client_factory: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> QuayRobotAccountsService:
    return QuayRobotAccountsService(
        quay_client_factory=mock_quay_client_factory,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )


def _repos(**permissions: str) -> list[QuayRobotRepository]:
    return [
        QuayRobotRepository(name=name, permission=permission)
        for name, permission in permissions.items()
    ]


def _org(
    token: Secret,
    *,
    robots: list[QuayRobotDesiredState] | None = None,
    managed_teams: list[str] | None = None,
    managed_repos: bool = True,
    managed_robot_accounts: bool = True,
) -> QuayOrgDesiredState:
    return QuayOrgDesiredState(
        instance_name="quay-io",
        instance_url="quay.io",
        org_name="test-org",
        token=token,
        managed_teams=managed_teams or ["team1", "team2"],
        managed_repos=managed_repos,
        managed_robot_accounts=managed_robot_accounts,
        robots=robots or [],
    )


def test_reconcile_no_changes(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.list_robot_accounts.return_value = [
        RobotAccount(name="ci-bot", teams=["team1"], repositories=["repo1"])
    ]
    mock_quay_client.get_robot_account_permissions.return_value = [
        RobotAccountPermission(
            repository=RobotAccountRepository(name="repo1"), role="read"
        )
    ]
    org = _org(
        test_token,
        robots=[
            QuayRobotDesiredState(
                name="ci-bot",
                teams=["team1"],
                repositories=_repos(repo1="read"),
            )
        ],
    )

    result = service.reconcile(organizations=[org], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_count == 0


def test_reconcile_create_robot_with_team_and_repo(
    service: QuayRobotAccountsService,
    test_token: Secret,
) -> None:
    org = _org(
        test_token,
        robots=[
            QuayRobotDesiredState(
                name="new-bot",
                description="New",
                teams=["team1"],
                repositories=_repos(repo1="read"),
            )
        ],
    )

    result = service.reconcile(organizations=[org], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 3
    assert isinstance(result.actions[0], QuayRobotActionCreate)
    assert result.actions[0].robot_name == "new-bot"
    assert isinstance(result.actions[1], QuayRobotActionAddTeam)
    assert result.actions[1].team == "team1"
    assert isinstance(result.actions[2], QuayRobotActionSetRepoPermission)
    assert result.actions[2].repo == "repo1"
    assert result.applied_count == 0


def test_reconcile_delete_robot(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.list_robot_accounts.return_value = [RobotAccount(name="old-bot")]
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="old-bot", delete=True)],
    )

    result = service.reconcile(organizations=[org], dry_run=True)

    assert len(result.actions) == 1
    assert isinstance(result.actions[0], QuayRobotActionDelete)


def test_reconcile_delete_robot_not_in_current(
    service: QuayRobotAccountsService, test_token: Secret
) -> None:
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="old-bot", delete=True)],
    )
    result = service.reconcile(organizations=[org], dry_run=True)
    assert result.actions == []


def test_reconcile_ignores_unmanaged_robots(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.list_robot_accounts.return_value = [
        RobotAccount(name="unmanaged"),
        RobotAccount(name="managed", teams=["team1"]),
    ]
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="managed", teams=["team1"])],
    )

    result = service.reconcile(organizations=[org], dry_run=True)

    assert result.actions == []
    mock_quay_client.get_robot_account_permissions.assert_called_once_with("managed")


def test_reconcile_team_changes(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.list_robot_accounts.return_value = [
        RobotAccount(name="bot", teams=["team1", "team2"])
    ]
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="bot", teams=["team1", "owners"])],
        managed_teams=["team1", "team2", "owners"],
    )

    result = service.reconcile(organizations=[org], dry_run=True)

    add = [a for a in result.actions if isinstance(a, QuayRobotActionAddTeam)]
    remove = [a for a in result.actions if isinstance(a, QuayRobotActionRemoveTeam)]
    assert [a.team for a in add] == ["owners"]
    assert [a.team for a in remove] == ["team2"]


def test_reconcile_repository_changes(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.list_robot_accounts.return_value = [RobotAccount(name="bot")]
    mock_quay_client.get_robot_account_permissions.return_value = [
        RobotAccountPermission(
            repository=RobotAccountRepository(name="repo1"), role="read"
        ),
        RobotAccountPermission(
            repository=RobotAccountRepository(name="repo2"), role="write"
        ),
    ]
    org = _org(
        test_token,
        robots=[
            QuayRobotDesiredState(
                name="bot",
                repositories=_repos(repo1="write", repo3="read"),
            )
        ],
    )

    result = service.reconcile(organizations=[org], dry_run=True)

    sets = [
        a for a in result.actions if isinstance(a, QuayRobotActionSetRepoPermission)
    ]
    removes = [
        a for a in result.actions if isinstance(a, QuayRobotActionRemoveRepoPermission)
    ]
    assert {a.repo for a in sets} == {"repo1", "repo3"}
    assert [a.repo for a in removes] == ["repo2"]


def test_validate_requires_managed_robot_accounts(
    service: QuayRobotAccountsService, test_token: Secret
) -> None:
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="bot")],
        managed_robot_accounts=False,
    )
    result = service.reconcile(organizations=[org], dry_run=True)
    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert any("managedRobotAccounts" in e for e in result.errors)


def test_validate_unmanaged_team(
    service: QuayRobotAccountsService, test_token: Secret
) -> None:
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="bot", teams=["owners"])],
    )
    result = service.reconcile(organizations=[org], dry_run=True)
    assert result.status == TaskStatus.FAILED
    assert any("managedTeam" in e for e in result.errors)


def test_validate_repos_require_managed_repos(
    service: QuayRobotAccountsService, test_token: Secret
) -> None:
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="bot", repositories=_repos(repo1="read"))],
        managed_repos=False,
    )
    result = service.reconcile(organizations=[org], dry_run=True)
    assert result.status == TaskStatus.FAILED
    assert any("managedRepos" in e for e in result.errors)


def test_filters_unmanaged_teams_from_current(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.list_robot_accounts.return_value = [
        RobotAccount(name="bot", teams=["team1", "owners"])
    ]
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="bot", teams=["team1"])],
        managed_repos=False,
    )
    result = service.reconcile(organizations=[org], dry_run=True)
    assert result.actions == []
    mock_quay_client.get_robot_account_permissions.assert_not_called()


def test_per_org_error_isolation(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client_factory: MagicMock,
    mock_quay_client: MagicMock,
) -> None:
    bad_org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="bot")],
        managed_robot_accounts=False,
    )
    good_org = QuayOrgDesiredState(
        instance_name="quay-io",
        instance_url="quay.io",
        org_name="good-org",
        token=test_token,
        managed_teams=["team1"],
        managed_repos=True,
        managed_robot_accounts=True,
        robots=[QuayRobotDesiredState(name="new-bot")],
    )
    mock_quay_client_factory.create_workspace_client.return_value = mock_quay_client

    result = service.reconcile(organizations=[bad_org, good_org], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert any("test-org" in e for e in result.errors)
    assert any(isinstance(a, QuayRobotActionCreate) for a in result.actions)


def test_apply_create_robot(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="new-bot", description="n")],
    )
    result = service.reconcile(organizations=[org], dry_run=False)
    mock_quay_client.create_robot_account.assert_called_once_with("new-bot", "n")
    mock_quay_client.close.assert_called_once()
    assert result.applied_count == 1
    assert result.status == TaskStatus.SUCCESS


def test_apply_create_succeeds_when_cache_lock_fails(
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
    test_token: Secret,
) -> None:
    mock_api = MagicMock(spec=QuayApi)
    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.get_obj.return_value = CachedRobotAccounts(items=[])
    mock_cache.lock.side_effect = RuntimeError("Could not acquire lock")
    client = QuayWorkspaceClient(
        quay_api=mock_api,
        instance_name="quay-io",
        organization="test-org",
        cache=mock_cache,
        settings=mock_settings,
    )
    factory = MagicMock()
    factory.create_workspace_client.return_value = client
    service = QuayRobotAccountsService(
        quay_client_factory=factory,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )
    org = _org(
        test_token,
        robots=[QuayRobotDesiredState(name="new-bot", description="n")],
    )

    result = service.reconcile(organizations=[org], dry_run=False)

    mock_api.create_robot_account.assert_called_once_with("new-bot", "n")
    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    assert result.errors == []


def test_apply_remaining_action_types(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.list_robot_accounts.return_value = [
        RobotAccount(name="keep", teams=["team1"], repositories=["repo1"]),
        RobotAccount(name="gone"),
    ]
    mock_quay_client.get_robot_account_permissions.return_value = [
        RobotAccountPermission(
            repository=RobotAccountRepository(name="repo1"), role="read"
        )
    ]
    org = _org(
        test_token,
        managed_teams=["team1", "team2"],
        robots=[
            QuayRobotDesiredState(
                name="keep",
                teams=["team2"],
                repositories=_repos(repo2="write"),
            ),
            QuayRobotDesiredState(name="gone", delete=True),
        ],
    )

    result = service.reconcile(organizations=[org], dry_run=False)

    mock_quay_client.delete_robot_account.assert_called_once_with("gone")
    mock_quay_client.add_robot_to_team.assert_called_once_with("keep", "team2")
    mock_quay_client.remove_robot_from_team.assert_called_once_with("keep", "team1")
    mock_quay_client.set_repo_robot_account_permissions.assert_called_once_with(
        "repo2", "keep", "write"
    )
    mock_quay_client.delete_repo_robot_account_permissions.assert_called_once_with(
        "repo1", "keep"
    )
    assert result.applied_count == 5
    assert result.status == TaskStatus.SUCCESS


def test_apply_action_error_collected(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client: MagicMock,
) -> None:
    mock_quay_client.create_robot_account.side_effect = RuntimeError("API Error")
    org = _org(test_token, robots=[QuayRobotDesiredState(name="new-bot")])
    result = service.reconcile(organizations=[org], dry_run=False)
    assert result.status == TaskStatus.FAILED
    assert result.applied_count == 0
    assert any("API Error" in e for e in result.errors)


def test_inventory_error_does_not_abort_other_orgs(
    service: QuayRobotAccountsService,
    test_token: Secret,
    mock_quay_client_factory: MagicMock,
) -> None:
    failing = MagicMock(spec=QuayWorkspaceClient)
    failing.list_robot_accounts.side_effect = RuntimeError("401")
    ok = MagicMock(spec=QuayWorkspaceClient)
    ok.list_robot_accounts.return_value = []
    ok.get_robot_account_permissions.return_value = []
    mock_quay_client_factory.create_workspace_client.side_effect = [failing, ok]

    org_a = _org(test_token, robots=[QuayRobotDesiredState(name="a")])
    org_b = QuayOrgDesiredState(
        instance_name="quay-io",
        instance_url="quay.io",
        org_name="other-org",
        token=test_token,
        managed_teams=[],
        managed_repos=False,
        managed_robot_accounts=True,
        robots=[QuayRobotDesiredState(name="b")],
    )

    result = service.reconcile(organizations=[org_a, org_b], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert any("test-org" in e and "401" in e for e in result.errors)
    assert any(a.robot_name == "b" for a in result.actions)
    failing.close.assert_called_once()
    ok.close.assert_called_once()


def test_duplicate_robot_names_rejected(test_token: Secret) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="duplicate robot names"):
        _org(
            test_token,
            robots=[
                QuayRobotDesiredState(name="bot"),
                QuayRobotDesiredState(name="bot"),
            ],
        )


def test_duplicate_repository_names_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="duplicate repository names"):
        QuayRobotDesiredState(
            name="bot",
            repositories=[
                QuayRobotRepository(name="images", permission="read"),
                QuayRobotRepository(name="images", permission="write"),
            ],
        )


def test_repositories_are_sorted_by_name() -> None:
    robot = QuayRobotDesiredState(
        name="bot",
        repositories=_repos(zeta="read", alpha="write"),
    )
    assert [repo.name for repo in robot.repositories] == ["alpha", "zeta"]
