from unittest.mock import create_autospec

import pytest

from reconcile.gql_definitions.quay_robot_accounts.quay_robot_accounts import (
    QuayInstanceV1,
    QuayOrgV1,
    QuayRepositoryV1,
    QuayRobotV1,
    VaultSecretV1,
)
from reconcile.quay_base import OrgKey, QuayApiStore
from reconcile.quay_robot_accounts import (
    RobotAccountAction,
    RobotAccountState,
    apply_action,
    build_current_state,
    build_desired_state,
    calculate_diff,
    get_current_robot_accounts,
)
from reconcile.utils.quay_api import QuayApi, RobotAccountDetails


@pytest.fixture
def mock_robot_gql() -> QuayRobotV1:
    """Mock robot account from GraphQL"""
    return QuayRobotV1(
        name="test-robot",
        description="Test robot account",
        quay_org=QuayOrgV1(
            name="test-org",
            instance=QuayInstanceV1(name="quay-instance", url="quay.io"),
            automationToken=VaultSecretV1(path="path", field="field", version=1),
        ),
        teams=["team1", "team2"],
        repositories=[
            QuayRepositoryV1(name="repo1", permission="read"),
            QuayRepositoryV1(name="repo2", permission="write"),
        ],
    )


@pytest.fixture
def mock_current_robot() -> RobotAccountDetails:
    """Mock current robot account from Quay API"""
    return RobotAccountDetails(
        name="existing-robot",
        description="Existing robot",
        teams=[{"name": "team1"}],
        repositories=[{"name": "repo1", "role": "read"}],
    )


@pytest.fixture
def mock_quay_api_store() -> QuayApiStore:
    """Mock QuayApiStore"""
    mock_api = create_autospec(QuayApi)
    mock_api.list_robot_accounts_detailed.return_value = []

    org_key = OrgKey("quay-instance", "test-org")
    return {
        org_key: {
            "api": mock_api,
            "push_token": None,
            "teams": [],
            "managedRepos": False,
            "mirror": None,
            "mirror_filters": {},
            "url": "quay.io",
        }
    }


def test_build_desired_state_single_robot(mock_robot_gql: QuayRobotV1) -> None:
    """Test building desired state with a single robot"""
    robots = [mock_robot_gql]
    desired_state: dict[tuple[str, str, str], RobotAccountState] = build_desired_state(
        robots
    )

    assert len(desired_state) == 1
    key = ("quay-instance", "test-org", "test-robot")
    assert key in desired_state

    state = desired_state[key]
    assert state.name == "test-robot"
    assert state.description == "Test robot account"
    assert state.org_name == "test-org"
    assert state.instance_name == "quay-instance"
    assert state.teams == {"team1", "team2"}
    assert state.repositories == {"repo1": "read", "repo2": "write"}


def test_build_desired_state_no_quay_org(mock_robot_gql: QuayRobotV1) -> None:
    """Test building desired state with robot without quay_org"""
    robot = QuayRobotV1(
        name="test-robot",
        description="Test robot",
        quay_org=None,
        teams=[],
        repositories=[],
    )

    desired_state: dict[tuple[str, str, str], RobotAccountState] = build_desired_state([
        robot
    ])
    assert len(desired_state) == 0


def test_build_desired_state_empty_teams_repos(mock_robot_gql: QuayRobotV1) -> None:
    """Test building desired state with empty teams and repositories"""
    robot = QuayRobotV1(
        name="test-robot",
        description="Test robot",
        quay_org=QuayOrgV1(
            name="test-org",
            instance=QuayInstanceV1(name="quay-instance", url="quay.io"),
            automationToken=None,
        ),
        teams=None,
        repositories=None,
    )

    desired_state: dict[tuple[str, str, str], RobotAccountState] = build_desired_state([
        robot
    ])
    key = ("quay-instance", "test-org", "test-robot")
    state = desired_state[key]

    assert state.teams == set()
    assert state.repositories == {}


def test_build_current_state_single_robot(
    mock_current_robot: RobotAccountDetails, mock_quay_api_store: QuayApiStore
) -> None:
    """Test building current state with a single robot"""
    current_robots = {("quay-instance", "test-org"): [mock_current_robot]}

    current_state: dict[tuple[str, str, str], RobotAccountState] = build_current_state(
        current_robots, mock_quay_api_store
    )

    assert len(current_state) == 1
    key = ("quay-instance", "test-org", "existing-robot")
    assert key in current_state

    state = current_state[key]
    assert state.name == "existing-robot"
    assert state.description == "Existing robot"
    assert state.teams == {"team1"}
    assert state.repositories == {"repo1": "read"}


def test_build_current_state_no_org_key(
    mock_current_robot: RobotAccountDetails,
) -> None:
    """Test building current state with no matching org key"""
    current_robots = {("unknown-instance", "unknown-org"): [mock_current_robot]}
    quay_api_store: QuayApiStore = {}

    current_state = build_current_state(current_robots, quay_api_store)
    assert len(current_state) == 0


def test_build_current_state_empty_robots(mock_quay_api_store: QuayApiStore) -> None:
    """Test building current state with empty robot list"""
    current_robots: dict[tuple[str, str], list[RobotAccountDetails]] = {
        ("quay-instance", "test-org"): []
    }

    current_state = build_current_state(current_robots, mock_quay_api_store)
    assert len(current_state) == 0


def test_calculate_diff_create_robot() -> None:
    """Test calculating diff when robot needs to be created"""
    desired_state: dict[tuple[str, str, str], RobotAccountState] = {
        ("instance", "org", "new-robot"): RobotAccountState(
            name="new-robot",
            description="New robot",
            org_name="org",
            instance_name="instance",
            teams={"team1"},
            repositories={"repo1": "read"},
        )
    }
    current_state: dict[tuple[str, str, str], RobotAccountState] = {}

    actions = calculate_diff(desired_state, current_state)

    assert len(actions) == 3  # create, add_team, set_repo_permission

    create_action = next(a for a in actions if a.action == "create")
    assert create_action.robot_name == "new-robot"
    assert create_action.org_name == "org"

    team_action = next(a for a in actions if a.action == "add_team")
    assert team_action.team == "team1"

    repo_action = next(a for a in actions if a.action == "set_repo_permission")
    assert repo_action.repo == "repo1"
    assert repo_action.permission == "read"


def test_calculate_diff_delete_robot() -> None:
    """Test calculating diff when robot needs to be deleted"""
    desired_state: dict[tuple[str, str, str], RobotAccountState] = {}
    current_state = {
        ("instance", "org", "old-robot"): RobotAccountState(
            name="old-robot",
            description="Old robot",
            org_name="org",
            instance_name="instance",
            teams=set(),
            repositories={},
        )
    }

    actions = calculate_diff(desired_state, current_state)

    assert len(actions) == 1
    assert actions[0].action == "delete"
    assert actions[0].robot_name == "old-robot"


def test_calculate_diff_team_changes() -> None:
    """Test calculating diff for team membership changes"""
    desired_state: dict[tuple[str, str, str], RobotAccountState] = {
        ("instance", "org", "robot"): RobotAccountState(
            name="robot",
            description="Robot",
            org_name="org",
            instance_name="instance",
            teams={"team1", "team3"},  # remove team2, add team3
            repositories={},
        )
    }
    current_state: dict[tuple[str, str, str], RobotAccountState] = {
        ("instance", "org", "robot"): RobotAccountState(
            name="robot",
            description="Robot",
            org_name="org",
            instance_name="instance",
            teams={"team1", "team2"},  # has team2, missing team3
            repositories={},
        )
    }

    actions = calculate_diff(desired_state, current_state)

    action_types = [a.action for a in actions]
    assert "add_team" in action_types
    assert "remove_team" in action_types

    add_action = next(a for a in actions if a.action == "add_team")
    assert add_action.team == "team3"

    remove_action = next(a for a in actions if a.action == "remove_team")
    assert remove_action.team == "team2"


def test_calculate_diff_repository_changes() -> None:
    """Test calculating diff for repository permission changes"""
    desired_state: dict[tuple[str, str, str], RobotAccountState] = {
        ("instance", "org", "robot"): RobotAccountState(
            name="robot",
            description="Robot",
            org_name="org",
            instance_name="instance",
            teams=set(),
            repositories={
                "repo1": "write",
                "repo3": "read",
            },  # change repo1, add repo3, remove repo2
        )
    }
    current_state: dict[tuple[str, str, str], RobotAccountState] = {
        ("instance", "org", "robot"): RobotAccountState(
            name="robot",
            description="Robot",
            org_name="org",
            instance_name="instance",
            teams=set(),
            repositories={
                "repo1": "read",
                "repo2": "write",
            },  # repo1 has different permission, repo2 should be removed
        )
    }

    actions = calculate_diff(desired_state, current_state)

    action_types = [a.action for a in actions]
    assert "set_repo_permission" in action_types
    assert "remove_repo_permission" in action_types

    set_actions = [a for a in actions if a.action == "set_repo_permission"]
    assert len(set_actions) == 2  # repo1 permission change, repo3 new

    remove_action = next(a for a in actions if a.action == "remove_repo_permission")
    assert remove_action.repo == "repo2"


def test_calculate_diff_no_changes() -> None:
    """Test calculating diff when no changes are needed"""
    state = RobotAccountState(
        name="robot",
        description="Robot",
        org_name="org",
        instance_name="instance",
        teams={"team1"},
        repositories={"repo1": "read"},
    )
    desired_state = {("instance", "org", "robot"): state}
    current_state = {("instance", "org", "robot"): state}

    actions = calculate_diff(desired_state, current_state)
    assert len(actions) == 0


def test_get_current_robot_accounts_success(mock_quay_api_store: QuayApiStore) -> None:
    """Test successful fetching of current robot accounts"""
    mock_robots = [
        RobotAccountDetails(
            name="robot1",
            description="Robot 1",
            teams=[{"name": "team1"}],
            repositories=[{"name": "repo1", "role": "read"}],
        ),
        RobotAccountDetails(
            name="robot2",
            description="Robot 2",
            teams=[{"name": "team2"}],
            repositories=[{"name": "repo2", "role": "write"}],
        ),
    ]
    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.list_robot_accounts_detailed.return_value = mock_robots  # type: ignore

    result = get_current_robot_accounts(mock_quay_api_store)

    assert len(result) == 1
    assert ("quay-instance", "test-org") in result
    assert result["quay-instance", "test-org"] == mock_robots


def test_get_current_robot_accounts_exception(
    mock_quay_api_store: QuayApiStore,
) -> None:
    """Test handling of exceptions when fetching robot accounts"""
    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.list_robot_accounts_detailed.side_effect = Exception("API Error")  # type: ignore

    result = get_current_robot_accounts(mock_quay_api_store)

    assert len(result) == 1
    assert result["quay-instance", "test-org"] == []


def test_apply_action_create_robot(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying create robot action"""
    action = RobotAccountAction(
        action="create",
        robot_name="new-robot",
        org_name="test-org",
        instance_name="quay-instance",
    )

    apply_action(action, mock_quay_api_store, dry_run=False)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.create_robot_account.assert_called_once_with("new-robot", "")  # type: ignore


def test_apply_action_delete_robot(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying delete robot action"""
    action = RobotAccountAction(
        action="delete",
        robot_name="old-robot",
        org_name="test-org",
        instance_name="quay-instance",
    )

    apply_action(action, mock_quay_api_store, dry_run=False)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.delete_robot_account.assert_called_once_with("old-robot")  # type: ignore


def test_apply_action_add_team(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying add team action"""
    action = RobotAccountAction(
        action="add_team",
        robot_name="robot",
        org_name="test-org",
        instance_name="quay-instance",
        team="new-team",
    )

    apply_action(action, mock_quay_api_store, dry_run=False)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.add_user_to_team.assert_called_once_with("test-org+robot", "new-team")  # type: ignore


def test_apply_action_remove_team(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying remove team action"""
    action = RobotAccountAction(
        action="remove_team",
        robot_name="robot",
        org_name="test-org",
        instance_name="quay-instance",
        team="old-team",
    )

    apply_action(action, mock_quay_api_store, dry_run=False)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.remove_user_from_team.assert_called_once_with("test-org+robot", "old-team")  # type: ignore


def test_apply_action_set_repo_permission(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying set repository permission action"""
    action = RobotAccountAction(
        action="set_repo_permission",
        robot_name="robot",
        org_name="test-org",
        instance_name="quay-instance",
        repo="repo1",
        permission="write",
    )

    apply_action(action, mock_quay_api_store, dry_run=False)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.set_repo_robot_permissions.assert_called_once_with(  # type: ignore[attr-defined]
        "repo1", "robot", "write"
    )


def test_apply_action_remove_repo_permission(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying remove repository permission action"""
    action = RobotAccountAction(
        action="remove_repo_permission",
        robot_name="robot",
        org_name="test-org",
        instance_name="quay-instance",
        repo="repo1",
    )

    apply_action(action, mock_quay_api_store, dry_run=False)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.delete_repo_robot_permissions.assert_called_once_with("repo1", "robot")  # type: ignore


def test_apply_action_dry_run(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying action in dry run mode"""
    action = RobotAccountAction(
        action="create",
        robot_name="new-robot",
        org_name="test-org",
        instance_name="quay-instance",
    )

    apply_action(action, mock_quay_api_store, dry_run=True)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.create_robot_account.assert_not_called()  # type: ignore


def test_apply_action_no_org_key(mock_quay_api_store: QuayApiStore) -> None:
    """Test applying action when org key is not found"""
    action = RobotAccountAction(
        action="create",
        robot_name="new-robot",
        org_name="unknown-org",
        instance_name="unknown-instance",
    )

    apply_action(action, mock_quay_api_store, dry_run=False)

    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.create_robot_account.assert_not_called()  # type: ignore


def test_apply_action_exception_handling(mock_quay_api_store: QuayApiStore) -> None:
    """Test exception handling in apply_action"""
    mock_api = mock_quay_api_store[next(iter(mock_quay_api_store.keys()))]["api"]
    mock_api.create_robot_account.side_effect = Exception("API Error")  # type: ignore

    action = RobotAccountAction(
        action="create",
        robot_name="new-robot",
        org_name="test-org",
        instance_name="quay-instance",
    )

    with pytest.raises(Exception, match="API Error"):
        apply_action(action, mock_quay_api_store, dry_run=False)
