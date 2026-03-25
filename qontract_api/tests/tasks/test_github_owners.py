"""Unit tests for github-owners Celery task — focusing on event publishing."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from qontract_api.integrations.github_owners.domain import GithubOrgDesiredState
from qontract_api.integrations.github_owners.schemas import (
    GithubOwnerActionAddOwner,
    GithubOwnersTaskResult,
)
from qontract_api.integrations.github_owners.tasks import (
    generate_lock_key,
    reconcile_github_owners_task,
)
from qontract_api.models import Secret, TaskStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_org() -> GithubOrgDesiredState:
    return GithubOrgDesiredState(
        org_name="my-org",
        owners=["alice", "bob"],
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path="app-sre/creds/github",
            field="token",
            version=1,
        ),
    )


@pytest.fixture
def mock_self() -> MagicMock:
    mock = MagicMock()
    mock.request.id = "test-task-id"
    return mock


def _task_func() -> Callable:
    """Return the unwrapped task function (bypasses Celery + deduplication decorators)."""
    return reconcile_github_owners_task.__wrapped__.__wrapped__


def _make_action(
    org: str = "my-org", username: str = "alice"
) -> GithubOwnerActionAddOwner:
    return GithubOwnerActionAddOwner(org_name=org, username=username)


def _make_result(
    applied_actions: list[GithubOwnerActionAddOwner] | None = None,
    errors: list[str] | None = None,
) -> GithubOwnersTaskResult:
    applied = applied_actions or []
    errs = errors or []
    return GithubOwnersTaskResult(
        status=TaskStatus.FAILED if errs else TaskStatus.SUCCESS,
        actions=applied,
        applied_actions=applied,
        applied_count=len(applied),
        errors=errs,
    )


# ---------------------------------------------------------------------------
# generate_lock_key
# ---------------------------------------------------------------------------


def test_generate_lock_key_single_org(sample_org: GithubOrgDesiredState) -> None:
    assert generate_lock_key(MagicMock(), [sample_org]) == "my-org"


def test_generate_lock_key_sorted() -> None:
    def _org(name: str) -> GithubOrgDesiredState:
        return GithubOrgDesiredState(
            org_name=name,
            owners=[],
            token=Secret(
                secret_manager_url="https://v", path="p", field="f", version=1
            ),
        )

    key = generate_lock_key(MagicMock(), [_org("org-b"), _org("org-a")])
    assert key == "org-a,org-b"


# ---------------------------------------------------------------------------
# Event publishing — success events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.github_owners.tasks.get_event_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_secret_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_cache")
@patch("qontract_api.integrations.github_owners.tasks.GithubOwnersService")
def test_publishes_success_event_for_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: GithubOrgDesiredState,
) -> None:
    """A success event is published for each successfully applied action."""
    action = _make_action()
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[action]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, [sample_org], dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.github-owners.add_owner"
    assert published.data["username"] == "alice"
    assert published.data["org_name"] == "my-org"


@patch("qontract_api.integrations.github_owners.tasks.get_event_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_secret_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_cache")
@patch("qontract_api.integrations.github_owners.tasks.GithubOwnersService")
def test_publishes_success_event_per_applied_action(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: GithubOrgDesiredState,
) -> None:
    """One success event is published per applied action."""
    actions = [_make_action(username="alice"), _make_action(username="bob")]
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=actions
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, [sample_org], dry_run=False)

    assert mock_event_manager.publish_event.call_count == 2
    types = [c[0][0].type for c in mock_event_manager.publish_event.call_args_list]
    assert all(t == "qontract-api.github-owners.add_owner" for t in types)


# ---------------------------------------------------------------------------
# Event publishing — error events
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.github_owners.tasks.get_event_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_secret_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_cache")
@patch("qontract_api.integrations.github_owners.tasks.GithubOwnersService")
def test_publishes_error_event_for_each_error(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: GithubOrgDesiredState,
) -> None:
    """An error event is published for each reconciliation error."""
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        errors=["my-org/alice: Failed to add owner: 403 Forbidden"]
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, [sample_org], dry_run=False)

    mock_event_manager.publish_event.assert_called_once()
    published = mock_event_manager.publish_event.call_args[0][0]
    assert published.type == "qontract-api.github-owners.error"
    assert "alice" in published.data["error"]


@patch("qontract_api.integrations.github_owners.tasks.get_event_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_secret_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_cache")
@patch("qontract_api.integrations.github_owners.tasks.GithubOwnersService")
def test_publishes_both_event_types_on_partial_failure(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: GithubOrgDesiredState,
) -> None:
    """Both success and error events are published when some actions apply and some fail."""
    mock_service_cls.return_value.reconcile.return_value = GithubOwnersTaskResult(
        status=TaskStatus.FAILED,
        actions=[_make_action("my-org", "alice"), _make_action("my-org", "bob")],
        applied_actions=[_make_action("my-org", "alice")],
        applied_count=1,
        errors=["my-org/bob: Failed to add owner: 403 Forbidden"],
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, [sample_org], dry_run=False)

    assert mock_event_manager.publish_event.call_count == 2
    event_types = {
        c[0][0].type for c in mock_event_manager.publish_event.call_args_list
    }
    assert event_types == {
        "qontract-api.github-owners.add_owner",
        "qontract-api.github-owners.error",
    }


# ---------------------------------------------------------------------------
# Event publishing — suppression cases
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.github_owners.tasks.get_event_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_secret_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_cache")
@patch("qontract_api.integrations.github_owners.tasks.GithubOwnersService")
def test_no_events_published_in_dry_run(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: GithubOrgDesiredState,
) -> None:
    """No events are published in dry-run mode."""
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[_make_action()],
        errors=["some error"],
    )
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    _task_func()(mock_self, [sample_org], dry_run=True)

    mock_event_manager.publish_event.assert_not_called()


@patch("qontract_api.integrations.github_owners.tasks.get_event_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_secret_manager")
@patch("qontract_api.integrations.github_owners.tasks.get_cache")
@patch("qontract_api.integrations.github_owners.tasks.GithubOwnersService")
def test_no_events_published_when_event_manager_disabled(
    mock_service_cls: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
    mock_self: MagicMock,
    sample_org: GithubOrgDesiredState,
) -> None:
    """No events are published when the event manager is not configured (returns None)."""
    mock_service_cls.return_value.reconcile.return_value = _make_result(
        applied_actions=[_make_action()],
        errors=["some error"],
    )
    mock_get_event_manager.return_value = None

    # Should not raise even with no event manager
    result = _task_func()(mock_self, [sample_org], dry_run=False)
    assert (
        result.status == TaskStatus.FAILED
    )  # errors present → failed, but no exception raised
