"""Unit tests for GitlabMembersService."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.gitlab_api import (
    GitlabAccessLevel,
    GitlabGroupMember,
    GitlabUser,
    GitlabUserNotFoundError,
)

from qontract_api.integrations.gitlab_members.domain import (
    GitlabMemberConfig,
    GitlabMembersGroupConfig,
    GitlabMembersInstanceConfig,
)
from qontract_api.integrations.gitlab_members.schemas import (
    GitlabMemberAction,
    GitlabMemberActionAdd,
    GitlabMemberActionChangeAccess,
    GitlabMemberActionRemove,
)
from qontract_api.integrations.gitlab_members.service import GitlabMembersService
from qontract_api.models import Secret, TaskStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = "test-token"
    return mock


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_settings() -> MagicMock:
    mock = MagicMock()
    mock.gitlab_projects.group_members_cache_ttl = 300
    mock.gitlab_projects.api_timeout = 30
    return mock


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    mock = MagicMock()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = None
    return mock


@pytest.fixture
def mock_workspace_client_factory(mock_workspace_client: MagicMock) -> MagicMock:
    return MagicMock(return_value=mock_workspace_client)


@pytest.fixture
def service(
    mock_secret_manager: MagicMock,
    mock_cache: MagicMock,
    mock_settings: MagicMock,
    mock_workspace_client_factory: MagicMock,
) -> GitlabMembersService:
    return GitlabMembersService(
        secret_manager=mock_secret_manager,
        cache=mock_cache,
        settings=mock_settings,
        workspace_client_factory=mock_workspace_client_factory,
    )


def _instance(
    name: str = "gitlab-cee",
    *,
    groups: list[GitlabMembersGroupConfig] | None = None,
) -> GitlabMembersInstanceConfig:
    return GitlabMembersInstanceConfig(
        name=name,
        url=f"https://{name}.example.com",
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path=f"secret/gitlab/{name}/token",
        ),
        groups=groups or [],
    )


def _group_cfg(
    group: str = "team", members: list[GitlabMemberConfig] | None = None
) -> GitlabMembersGroupConfig:
    return GitlabMembersGroupConfig(group=group, members=members or [])


def _member_cfg(
    username: str = "jsmith",
    access_level: GitlabAccessLevel = GitlabAccessLevel.DEVELOPER,
) -> GitlabMemberConfig:
    return GitlabMemberConfig(username=username, access_level=access_level)


def _gitlab_member(
    member_id: int = 1,
    username: str = "jsmith",
    name: str = "Jane Smith",
    access_level: int = 30,
) -> GitlabGroupMember:
    return GitlabGroupMember(
        id=member_id, username=username, name=name, access_level=access_level
    )


def _gitlab_user(
    user_id: int = 1, username: str = "jsmith", name: str = "Jane Smith"
) -> GitlabUser:
    return GitlabUser(id=user_id, username=username, name=name)


# ---------------------------------------------------------------------------
# _calculate_actions
# ---------------------------------------------------------------------------


def test_calculate_actions_adds_missing_member(
    mock_workspace_client: MagicMock,
) -> None:
    mock_workspace_client.get_user_by_username.return_value = _gitlab_user(
        user_id=7, username="jsmith"
    )

    actions, errors = GitlabMembersService._calculate_actions(
        mock_workspace_client,
        "gitlab-cee",
        _group_cfg(
            members=[
                _member_cfg(username="jsmith", access_level=GitlabAccessLevel.DEVELOPER)
            ]
        ),
        current_members=[],
    )

    assert errors == []
    assert len(actions) == 1
    assert isinstance(actions[0], GitlabMemberActionAdd)
    assert actions[0].username == "jsmith"
    assert actions[0].user_id == 7
    assert actions[0].access_level == GitlabAccessLevel.DEVELOPER
    mock_workspace_client.get_user_by_username.assert_called_once_with("jsmith")


def test_calculate_actions_skips_add_when_user_not_found(
    mock_workspace_client: MagicMock,
) -> None:
    mock_workspace_client.get_user_by_username.side_effect = GitlabUserNotFoundError(
        "jsmith"
    )

    actions, errors = GitlabMembersService._calculate_actions(
        mock_workspace_client,
        "gitlab-cee",
        _group_cfg(members=[_member_cfg(username="jsmith")]),
        current_members=[],
    )

    assert actions == []
    assert len(errors) == 1
    assert "jsmith" in errors[0]
    assert "not found" in errors[0]


def test_calculate_actions_removes_member_not_in_desired(
    mock_workspace_client: MagicMock,
) -> None:
    actions, errors = GitlabMembersService._calculate_actions(
        mock_workspace_client,
        "gitlab-cee",
        _group_cfg(members=[]),
        current_members=[_gitlab_member(member_id=9, username="stale")],
    )

    assert errors == []
    assert len(actions) == 1
    assert isinstance(actions[0], GitlabMemberActionRemove)
    assert actions[0].username == "stale"
    assert actions[0].member_id == 9


def test_calculate_actions_changes_access_level(
    mock_workspace_client: MagicMock,
) -> None:
    actions, errors = GitlabMembersService._calculate_actions(
        mock_workspace_client,
        "gitlab-cee",
        _group_cfg(
            members=[
                _member_cfg(
                    username="jsmith", access_level=GitlabAccessLevel.MAINTAINER
                )
            ]
        ),
        current_members=[
            _gitlab_member(member_id=5, username="jsmith", access_level=30)
        ],
    )

    assert errors == []
    assert len(actions) == 1
    assert isinstance(actions[0], GitlabMemberActionChangeAccess)
    assert actions[0].member_id == 5
    assert actions[0].access_level == GitlabAccessLevel.MAINTAINER


def test_calculate_actions_no_change_when_identical(
    mock_workspace_client: MagicMock,
) -> None:
    actions, errors = GitlabMembersService._calculate_actions(
        mock_workspace_client,
        "gitlab-cee",
        _group_cfg(
            members=[
                _member_cfg(username="jsmith", access_level=GitlabAccessLevel.DEVELOPER)
            ]
        ),
        current_members=[
            _gitlab_member(member_id=5, username="jsmith", access_level=30)
        ],
    )

    assert actions == []
    assert errors == []


# ---------------------------------------------------------------------------
# _apply_actions
# ---------------------------------------------------------------------------


def test_apply_actions_add_success(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    actions: list[GitlabMemberAction] = [
        GitlabMemberActionAdd(
            instance="i",
            group="team",
            username="jsmith",
            user_id=7,
            access_level=GitlabAccessLevel.DEVELOPER,
        )
    ]

    applied, errors = service._apply_actions(
        mock_workspace_client, "i", "team", actions
    )

    assert applied == actions
    assert errors == []
    mock_workspace_client.add_group_member.assert_called_once_with(
        "team", 7, GitlabAccessLevel.DEVELOPER
    )


def test_apply_actions_remove_success(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    actions: list[GitlabMemberAction] = [
        GitlabMemberActionRemove(
            instance="i", group="team", username="stale", member_id=9
        )
    ]

    applied, errors = service._apply_actions(
        mock_workspace_client, "i", "team", actions
    )

    assert applied == actions
    assert errors == []
    mock_workspace_client.remove_group_member.assert_called_once_with("team", 9)


def test_apply_actions_change_access_success(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    actions: list[GitlabMemberAction] = [
        GitlabMemberActionChangeAccess(
            instance="i",
            group="team",
            username="jsmith",
            member_id=5,
            access_level=GitlabAccessLevel.MAINTAINER,
        )
    ]

    applied, errors = service._apply_actions(
        mock_workspace_client, "i", "team", actions
    )

    assert applied == actions
    assert errors == []
    mock_workspace_client.update_group_member_access.assert_called_once_with(
        "team", 5, GitlabAccessLevel.MAINTAINER
    )


def test_apply_actions_failed_action_reports_error(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.add_group_member.side_effect = RuntimeError("boom")
    actions: list[GitlabMemberAction] = [
        GitlabMemberActionAdd(
            instance="i",
            group="team",
            username="jsmith",
            user_id=7,
            access_level=GitlabAccessLevel.DEVELOPER,
        )
    ]

    applied, errors = service._apply_actions(
        mock_workspace_client, "i", "team", actions
    )

    assert applied == []
    assert len(errors) == 1
    assert "boom" in errors[0]


def test_apply_actions_isolates_errors_across_actions(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    def add_side_effect(
        _group: str, user_id: int, _access_level: GitlabAccessLevel
    ) -> None:
        if user_id == 1:
            raise RuntimeError("boom")

    mock_workspace_client.add_group_member.side_effect = add_side_effect
    actions: list[GitlabMemberAction] = [
        GitlabMemberActionAdd(
            instance="i",
            group="team",
            username="bad",
            user_id=1,
            access_level=GitlabAccessLevel.DEVELOPER,
        ),
        GitlabMemberActionAdd(
            instance="i",
            group="team",
            username="good",
            user_id=2,
            access_level=GitlabAccessLevel.DEVELOPER,
        ),
    ]

    applied, errors = service._apply_actions(
        mock_workspace_client, "i", "team", actions
    )

    assert [a.username for a in applied] == ["good"]
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# reconcile — dry_run
# ---------------------------------------------------------------------------


def test_reconcile_dry_run_computes_actions_without_applying(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group_members.return_value = []
    mock_workspace_client.get_user_by_username.return_value = _gitlab_user()
    instances = [_instance(groups=[_group_cfg(members=[_member_cfg()])])]

    result = service.reconcile(instances, dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.applied_actions == []
    assert result.applied_count == 0
    mock_workspace_client.add_group_member.assert_not_called()


def test_reconcile_non_dry_run_applies_actions(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group_members.return_value = []
    mock_workspace_client.get_user_by_username.return_value = _gitlab_user(user_id=7)
    instances = [_instance(groups=[_group_cfg(members=[_member_cfg()])])]

    result = service.reconcile(instances, dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    mock_workspace_client.add_group_member.assert_called_once()


# ---------------------------------------------------------------------------
# reconcile — error isolation
# ---------------------------------------------------------------------------


def test_reconcile_isolates_errors_across_groups(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    def get_group_members_side_effect(group: str) -> list[GitlabGroupMember]:
        if group == "bad-group":
            raise RuntimeError("group not found")
        return []

    mock_workspace_client.get_group_members.side_effect = get_group_members_side_effect
    mock_workspace_client.get_user_by_username.return_value = _gitlab_user()
    instances = [
        _instance(
            groups=[
                _group_cfg(group="bad-group", members=[_member_cfg()]),
                _group_cfg(group="good-group", members=[_member_cfg()]),
            ]
        )
    ]

    result = service.reconcile(instances, dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "bad-group" in result.errors[0]
    assert any(a.group == "good-group" for a in result.actions)


def test_reconcile_isolates_errors_across_instances(
    mock_secret_manager: MagicMock,
    mock_cache: MagicMock,
    mock_settings: MagicMock,
) -> None:
    good_client = MagicMock()
    good_client.__enter__.return_value = good_client
    good_client.__exit__.return_value = None
    good_client.get_group_members.return_value = [
        _gitlab_member(member_id=1, username="jsmith", access_level=30)
    ]

    def factory(**kwargs: object) -> MagicMock:
        if kwargs["url"] == "https://bad-instance.example.com":
            raise RuntimeError("auth failed")
        return good_client

    service = GitlabMembersService(
        secret_manager=mock_secret_manager,
        cache=mock_cache,
        settings=mock_settings,
        workspace_client_factory=factory,
    )
    instances = [
        _instance(name="bad-instance", groups=[_group_cfg(members=[_member_cfg()])]),
        _instance(
            name="good-instance",
            groups=[_group_cfg(members=[_member_cfg(username="jsmith")])],
        ),
    ]

    result = service.reconcile(instances, dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "bad-instance" in result.errors[0]
    # good-instance must still be reconciled despite bad-instance's failure
    assert result.actions == []  # jsmith already a member per good_client


def test_reconcile_error_calculating_user_lookup_reported(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group_members.return_value = []
    mock_workspace_client.get_user_by_username.side_effect = GitlabUserNotFoundError(
        "jsmith"
    )
    instances = [_instance(groups=[_group_cfg(members=[_member_cfg()])])]

    result = service.reconcile(instances, dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert len(result.errors) == 1
    assert "jsmith" in result.errors[0]


def test_reconcile_success_status_when_no_errors(
    service: GitlabMembersService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group_members.return_value = []

    result = service.reconcile([_instance()], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.errors == []
