"""Tests for gitlab-members tasks."""

import inspect
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.gitlab_api import GitlabAccessLevel

from qontract_api.integrations.gitlab_members.domain import (
    GitlabMemberConfig,
    GitlabMembersGroupConfig,
    GitlabMembersInstanceConfig,
)
from qontract_api.integrations.gitlab_members.schemas import (
    GitlabMemberActionAdd,
    GitlabMembersTaskResult,
)
from qontract_api.integrations.gitlab_members.tasks import (
    generate_lock_key,
    reconcile_gitlab_members_task,
)
from qontract_api.models import Secret, TaskStatus


@pytest.fixture
def mock_self() -> MagicMock:
    mock = MagicMock()
    mock.request.id = "test-task-id"
    return mock


def _make_group(
    group: str = "a-group",
    members: list[GitlabMemberConfig] | None = None,
) -> GitlabMembersGroupConfig:
    return GitlabMembersGroupConfig(group=group, members=members or [])


def _make_instance(
    name: str = "gitlab-cee", groups: list[GitlabMembersGroupConfig] | None = None
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


def _task_func() -> Callable:
    """Return the unwrapped task function (bypasses Celery + deduplication decorators)."""
    return inspect.unwrap(reconcile_gitlab_members_task)


def _make_add_action(
    instance: str = "a-instance",
    group: str = "a-group",
    username: str = "jsmith",
    user_id: int = 7,
    access_level: GitlabAccessLevel = GitlabAccessLevel.DEVELOPER,
) -> GitlabMemberActionAdd:
    return GitlabMemberActionAdd(
        instance=instance,
        group=group,
        username=username,
        user_id=user_id,
        access_level=access_level,
    )


def _make_result(
    applied_actions: list[GitlabMemberActionAdd] | None = None,
    errors: list[str] | None = None,
) -> GitlabMembersTaskResult:
    applied = applied_actions or []
    errs = errors or []
    return GitlabMembersTaskResult(
        status=TaskStatus.FAILED if errs else TaskStatus.SUCCESS,
        actions=applied,
        applied_actions=applied,
        applied_count=len(applied),
        errors=errs,
    )


# ---------------------------------------------------------------------------
# generate_lock_key
# ---------------------------------------------------------------------------


def test_generate_lock_key_sorted() -> None:
    """Lock key is sorted instance names."""
    instances = [_make_instance("z-instance"), _make_instance("a-instance")]
    key = generate_lock_key(MagicMock(), instances)
    assert key == "a-instance,z-instance"


def test_generate_lock_key_single() -> None:
    key = generate_lock_key(MagicMock(), [_make_instance("gitlab-cee")])
    assert key == "gitlab-cee"


def test_generate_lock_key_empty() -> None:
    key = generate_lock_key(MagicMock(), [])
    assert key == ""


# ---------------------------------------------------------------------------
# Event publishing — success events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.gitlab_members.tasks.get_event_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_secret_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_cache")
@patch("qontract_api.integrations.gitlab_members.tasks.GitlabMembersService")
def test_publishes_success_event_for_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    action = _make_add_action(instance="a-instance", group="a-group", username="jsmith")
    instance = _make_instance(
        name="a-instance",
        groups=[
            _make_group(
                group="a-group",
                members=[
                    GitlabMemberConfig(
                        username="jsmith", access_level=GitlabAccessLevel.DEVELOPER
                    )
                ],
            )
        ],
    )
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, instances=[instance], dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.gitlab-members.add_member"
    assert published.data["instance"] == "a-instance"
    assert published.data["group"] == "a-group"
    assert published.data["username"] == "jsmith"


@patch("qontract_api.integrations.gitlab_members.tasks.get_event_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_secret_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_cache")
@patch("qontract_api.integrations.gitlab_members.tasks.GitlabMembersService")
def test_publishes_one_event_per_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    actions = [
        _make_add_action("a-instance", "a-group", "jsmith"),
        _make_add_action("a-instance", "a-group", "mdoe"),
    ]
    instance = _make_instance(
        name="a-instance",
        groups=[
            _make_group(
                group="a-group",
                members=[
                    GitlabMemberConfig(
                        username="jsmith", access_level=GitlabAccessLevel.DEVELOPER
                    ),
                    GitlabMemberConfig(
                        username="mdoe", access_level=GitlabAccessLevel.DEVELOPER
                    ),
                ],
            )
        ],
    )
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=actions
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, instances=[instance], dry_run=False)

    assert mock_event_manager.publish_event.call_count == 2
    types = {c[0][0].type for c in mock_event_manager.publish_event.call_args_list}
    assert types == {"qontract-api.gitlab-members.add_member"}


# ---------------------------------------------------------------------------
# Event publishing — error events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.gitlab_members.tasks.get_event_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_secret_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_cache")
@patch("qontract_api.integrations.gitlab_members.tasks.GitlabMembersService")
def test_publishes_error_event_for_each_error(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    instance = _make_instance(
        name="a-instance",
        groups=[
            _make_group(
                group="a-group",
                members=[
                    GitlabMemberConfig(
                        username="jsmith", access_level=GitlabAccessLevel.DEVELOPER
                    )
                ],
            )
        ],
    )
    error = "a-instance/a-group/jsmith/add_member: boom"
    mock_service_cls.return_value.reconcile.return_value = _make_result(errors=[error])
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, instances=[instance], dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.gitlab-members.error"
    assert error in published.data["error"]


# ---------------------------------------------------------------------------
# Event publishing — suppression cases
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.gitlab_members.tasks.get_event_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_secret_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_cache")
@patch("qontract_api.integrations.gitlab_members.tasks.GitlabMembersService")
def test_no_events_published_in_dry_run(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    action = _make_add_action(instance="a-instance", group="a-group", username="jsmith")
    instance = _make_instance(
        name="a-instance",
        groups=[
            _make_group(
                group="a-group",
                members=[
                    GitlabMemberConfig(
                        username="jsmith", access_level=GitlabAccessLevel.DEVELOPER
                    )
                ],
            )
        ],
    )
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action], errors=["some error"]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, instances=[instance], dry_run=True)

    mock_event_manager.publish_event.assert_not_called()


@patch("qontract_api.integrations.gitlab_members.tasks.get_event_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_secret_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_cache")
@patch("qontract_api.integrations.gitlab_members.tasks.GitlabMembersService")
def test_no_events_published_when_event_manager_disabled(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    action = _make_add_action(instance="a-instance", group="a-group", username="jsmith")
    instance = _make_instance(
        name="a-instance",
        groups=[
            _make_group(
                group="a-group",
                members=[
                    GitlabMemberConfig(
                        username="jsmith", access_level=GitlabAccessLevel.DEVELOPER
                    )
                ],
            )
        ],
    )
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action], errors=["some error"]
    )
    mock_get_event_manager.return_value = None

    result = _task_func()(mock_self, instances=[instance], dry_run=False)
    assert result.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.gitlab_members.tasks.get_event_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_secret_manager")
@patch("qontract_api.integrations.gitlab_members.tasks.get_cache")
@patch("qontract_api.integrations.gitlab_members.tasks.GitlabMembersService")
def test_task_returns_failed_result_on_unexpected_exception(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
) -> None:
    instance = _make_instance(
        name="a-instance",
        groups=[
            _make_group(
                group="a-group",
                members=[
                    GitlabMemberConfig(
                        username="jsmith", access_level=GitlabAccessLevel.DEVELOPER
                    )
                ],
            )
        ],
    )
    mock_service_cls.return_value.reconcile.side_effect = RuntimeError(
        "connection refused"
    )

    result = _task_func()(mock_self, instances=[instance], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert "connection refused" in result.errors[0]
