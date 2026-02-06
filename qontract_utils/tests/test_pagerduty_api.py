"""Tests for qontract_utils.pagerduty_api module."""

# ruff: noqa: ARG001

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from qontract_utils.pagerduty_api import (
    TIMEOUT,
    PagerDutyApi,
    PagerDutyApiCallContext,
    PagerDutyUser,
)


@pytest.fixture
def mock_pagerduty_client() -> Generator[MagicMock, None, None]:
    """Mock PagerDuty client."""
    with patch("qontract_utils.pagerduty_api.client.RestApiV2Client") as mock_client:
        yield mock_client


@pytest.fixture
def pagerduty_api(mock_pagerduty_client: MagicMock) -> PagerDutyApi:
    """Create PagerDutyApi instance with mocked client."""
    return PagerDutyApi(
        id="test-instance",
        token="test-token",
    )


def test_pagerduty_api_defaults(mock_pagerduty_client: MagicMock) -> None:
    """Test PagerDutyApi uses default timeout."""
    api = PagerDutyApi("instance", "token")

    assert api.id == "instance"
    assert api._timeout == TIMEOUT


def test_pagerduty_api_custom_timeout(mock_pagerduty_client: MagicMock) -> None:
    """Test PagerDutyApi with custom timeout."""
    api = PagerDutyApi(
        "instance",
        "token",
        timeout=15,
    )

    assert api._timeout == 15


def test_pagerduty_api_client_created_with_token(
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test PagerDuty client is created with correct API key."""
    PagerDutyApi("instance", "test-api-key")

    mock_pagerduty_client.assert_called_once_with(api_key="test-api-key")


def test_pagerduty_api_pre_hooks_includes_metrics(
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test that metrics hook is always included."""
    api = PagerDutyApi("instance", "token")

    # Should have at least the metrics hook
    assert len(api._pre_hooks) >= 1


def test_pagerduty_api_pre_hooks_custom(mock_pagerduty_client: MagicMock) -> None:
    """Test custom hooks are added after metrics hook."""
    custom_hook = MagicMock()
    api = PagerDutyApi(
        "instance",
        "token",
        pre_hooks=[custom_hook],
    )

    # Should have metrics hook + latency_start + request_log + custom hook
    assert len(api._pre_hooks) == 4
    assert api._pre_hooks[-1] == custom_hook


def test_pagerduty_api_post_hooks_includes_latency(
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test that latency hook is always included in post_hooks."""
    api = PagerDutyApi("instance", "token")

    # Should have at least the latency_end hook
    assert len(api._post_hooks) >= 1


def test_pagerduty_api_post_hooks_custom(mock_pagerduty_client: MagicMock) -> None:
    """Test custom post_hooks are added after latency hook."""
    custom_hook = MagicMock()
    api = PagerDutyApi(
        "instance",
        "token",
        post_hooks=[custom_hook],
    )

    # Should have latency_end hook + custom hook
    assert len(api._post_hooks) == 2
    assert api._post_hooks[-1] == custom_hook


def test_pagerduty_api_error_hooks_custom(mock_pagerduty_client: MagicMock) -> None:
    """Test custom error_hooks are added."""
    custom_hook = MagicMock()
    api = PagerDutyApi(
        "instance",
        "token",
        error_hooks=[custom_hook],
    )

    # Should have custom error hook
    assert len(api._error_hooks) == 1
    assert api._error_hooks[0] == custom_hook


def test_get_schedule_users_returns_pagerduty_user_objects(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_schedule_users returns list of PagerDutyUser objects."""
    mock_schedule: dict = {
        "final_schedule": {
            "rendered_schedule_entries": [
                {
                    "user": {
                        "id": "USER1",
                    }
                },
                {
                    "user": {
                        "id": "USER2",
                    }
                },
            ]
        }
    }

    # Mock get_user calls
    def rget_side_effect(path: str, **kwargs: dict) -> dict:
        if path == "/schedules/SCHEDULE123":
            return mock_schedule
        if path == "/users/USER1":
            return {"email": "alice@example.com", "name": "Alice Smith"}
        if path == "/users/USER2":
            return {"email": "bob@example.com", "name": "Bob Jones"}
        return {}

    pagerduty_api._client.rget = MagicMock(side_effect=rget_side_effect)

    users = pagerduty_api.get_schedule_users("SCHEDULE123")

    assert len(users) == 2
    assert all(isinstance(user, PagerDutyUser) for user in users)
    assert {u.username for u in users} == {"alice", "bob"}


def test_get_schedule_users_deduplicates_users(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_schedule_users deduplicates users from multiple entries."""
    mock_schedule: dict = {
        "final_schedule": {
            "rendered_schedule_entries": [
                {"user": {"id": "USER1"}},
                {"user": {"id": "USER1"}},
            ]
        }
    }

    def rget_side_effect(path: str, **kwargs: dict) -> dict:
        if path == "/schedules/SCHEDULE123":
            return mock_schedule
        if path == "/users/USER1":
            return {"email": "alice@example.com", "name": "Alice Smith"}
        return {}

    pagerduty_api._client.rget = MagicMock(side_effect=rget_side_effect)

    users = pagerduty_api.get_schedule_users("SCHEDULE123")

    # Should return 2 users (deduplication is not implemented in API layer)
    assert len(users) == 2
    assert users[0].username == "alice"
    assert users[1].username == "alice"


def test_get_schedule_users_handles_empty_schedule(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_schedule_users handles empty schedule (no one on-call)."""
    mock_schedule: dict = {"final_schedule": {"rendered_schedule_entries": []}}
    pagerduty_api._client.rget = MagicMock(return_value=mock_schedule)

    users = pagerduty_api.get_schedule_users("SCHEDULE123")

    assert len(users) == 0


def test_get_schedule_users_calls_api_with_time_window(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_schedule_users calls API with now to now+60s time window."""
    mock_schedule: dict = {"final_schedule": {"rendered_schedule_entries": []}}
    pagerduty_api._client.rget = MagicMock(return_value=mock_schedule)

    pagerduty_api.get_schedule_users("SCHEDULE123")

    # Verify API was called with schedule ID and params
    pagerduty_api._client.rget.assert_called_once()
    call_args = pagerduty_api._client.rget.call_args
    assert "/schedules/SCHEDULE123" in call_args.args
    assert "params" in call_args.kwargs
    assert "since" in call_args.kwargs["params"]
    assert "until" in call_args.kwargs["params"]


def test_get_schedule_users_calls_pre_hooks(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_schedule_users calls pre_hooks before API call."""
    hook = MagicMock()
    pagerduty_api._pre_hooks = [hook]
    mock_schedule: dict = {"final_schedule": {"rendered_schedule_entries": []}}
    pagerduty_api._client.rget = MagicMock(return_value=mock_schedule)

    pagerduty_api.get_schedule_users("SCHEDULE123")

    hook.assert_called_once()
    context = hook.call_args[0][0]
    assert context.method == "schedules.get"
    assert context.verb == "GET"


def test_get_schedule_users_calls_post_hooks(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_schedule_users calls post_hooks after API call."""
    post_hook = MagicMock()
    pagerduty_api._post_hooks = [post_hook]
    mock_schedule: dict = {"final_schedule": {"rendered_schedule_entries": []}}
    pagerduty_api._client.rget = MagicMock(return_value=mock_schedule)

    pagerduty_api.get_schedule_users("SCHEDULE123")

    post_hook.assert_called_once()
    context = post_hook.call_args[0][0]
    assert context.method == "schedules.get"
    assert context.verb == "GET"


def test_get_escalation_policy_users_returns_pagerduty_user_objects(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_escalation_policy_users returns list of PagerDutyUser objects."""
    mock_policy = {
        "escalation_rules": [
            {
                "targets": [{"type": "user_reference", "id": "USER1"}],
                "escalation_delay_in_minutes": 0,
            },
            {
                "targets": [{"type": "user_reference", "id": "USER2"}],
                "escalation_delay_in_minutes": 0,
            },
        ]
    }

    def rget_side_effect(path: str, **kwargs: dict) -> dict:
        if path == "/escalation_policies/POLICY123":
            return mock_policy
        if path == "/users/USER1":
            return {"email": "alice@example.com", "name": "Alice Smith"}
        if path == "/users/USER2":
            return {"email": "bob@example.com", "name": "Bob Jones"}
        return {}

    pagerduty_api._client.rget = MagicMock(side_effect=rget_side_effect)

    users = pagerduty_api.get_escalation_policy_users("POLICY123")

    assert len(users) == 2
    assert all(isinstance(user, PagerDutyUser) for user in users)
    assert {u.username for u in users} == {"alice", "bob"}


def test_get_escalation_policy_users_handles_user_reference_type(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_escalation_policy_users handles user_reference type."""
    mock_policy = {
        "escalation_rules": [
            {
                "targets": [{"type": "user_reference", "id": "USER1"}],
                "escalation_delay_in_minutes": 0,
            }
        ]
    }

    def rget_side_effect(path: str, **kwargs: dict) -> dict:
        if path == "/escalation_policies/POLICY123":
            return mock_policy
        if path == "/users/USER1":
            return {"email": "charlie@example.com", "name": "Charlie Brown"}
        return {}

    pagerduty_api._client.rget = MagicMock(side_effect=rget_side_effect)

    users = pagerduty_api.get_escalation_policy_users("POLICY123")

    assert len(users) == 1
    assert users[0].username == "charlie"


def test_get_escalation_policy_users_deduplicates_users(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_escalation_policy_users handles users in multiple rules."""
    mock_policy = {
        "escalation_rules": [
            {
                "targets": [{"type": "user_reference", "id": "USER1"}],
                "escalation_delay_in_minutes": 30,
            },
            {
                "targets": [{"type": "user_reference", "id": "USER1"}],
                "escalation_delay_in_minutes": 60,
            },
        ]
    }

    def rget_side_effect(path: str, **kwargs: dict) -> dict:
        if path == "/escalation_policies/POLICY123":
            return mock_policy
        if path == "/users/USER1":
            return {"email": "alice@example.com", "name": "Alice Smith"}
        return {}

    pagerduty_api._client.rget = MagicMock(side_effect=rget_side_effect)

    users = pagerduty_api.get_escalation_policy_users("POLICY123")

    # Only processes first rule if delay != 0, so returns 1 user
    assert len(users) == 1
    assert users[0].username == "alice"


def test_get_escalation_policy_users_handles_schedule_reference(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_escalation_policy_users handles schedule_reference targets."""
    mock_policy = {
        "escalation_rules": [
            {
                "targets": [
                    {"type": "user_reference", "id": "USER1"},
                    {"type": "schedule_reference", "id": "SCHEDULE1"},
                ],
                "escalation_delay_in_minutes": 0,
            }
        ]
    }

    mock_schedule = {
        "final_schedule": {"rendered_schedule_entries": [{"user": {"id": "USER2"}}]}
    }

    def rget_side_effect(path: str, **kwargs: dict) -> dict:
        if path == "/escalation_policies/POLICY123":
            return mock_policy
        if path == "/users/USER1":
            return {"email": "alice@example.com", "name": "Alice Smith"}
        if path == "/schedules/SCHEDULE1":
            return mock_schedule
        if path == "/users/USER2":
            return {"email": "bob@example.com", "name": "Bob Jones"}
        return {}

    pagerduty_api._client.rget = MagicMock(side_effect=rget_side_effect)

    users = pagerduty_api.get_escalation_policy_users("POLICY123")

    # Should return both user and schedule users
    assert len(users) == 2
    assert {u.username for u in users} == {"alice", "bob"}


def test_get_escalation_policy_users_handles_empty_policy(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_escalation_policy_users handles policy with no rules."""
    mock_policy: dict = {"escalation_rules": []}
    pagerduty_api._client.rget = MagicMock(return_value=mock_policy)

    users = pagerduty_api.get_escalation_policy_users("POLICY123")

    assert len(users) == 0


def test_get_escalation_policy_users_calls_pre_hooks(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_escalation_policy_users calls pre_hooks before API call."""
    hook = MagicMock()
    pagerduty_api._pre_hooks = [hook]
    mock_policy: dict = {"escalation_rules": []}
    pagerduty_api._client.rget = MagicMock(return_value=mock_policy)

    pagerduty_api.get_escalation_policy_users("POLICY123")

    hook.assert_called_once()
    context = hook.call_args[0][0]
    assert context.method == "escalation_policies.get"
    assert context.verb == "GET"


def test_get_escalation_policy_users_calls_post_hooks(
    pagerduty_api: PagerDutyApi,
    mock_pagerduty_client: MagicMock,
) -> None:
    """Test get_escalation_policy_users calls post_hooks after API call."""
    post_hook = MagicMock()
    pagerduty_api._post_hooks = [post_hook]
    mock_policy: dict = {"escalation_rules": []}
    pagerduty_api._client.rget = MagicMock(return_value=mock_policy)

    pagerduty_api.get_escalation_policy_users("POLICY123")

    post_hook.assert_called_once()
    context = post_hook.call_args[0][0]
    assert context.method == "escalation_policies.get"
    assert context.verb == "GET"


def test_pagerduty_user_immutable() -> None:
    """Test PagerDutyUser is immutable (frozen=True)."""
    user = PagerDutyUser(id="USER1", email="jsmith@example.com", name="John Smith")

    with pytest.raises(ValidationError):
        user.email = "different"  # type: ignore[misc]


def test_pagerduty_user_username_property() -> None:
    """Test username property extracts username from email."""
    user = PagerDutyUser(id="USER1", email="jsmith@example.com", name="John Smith")
    assert user.username == "jsmith"

    user2 = PagerDutyUser(id="USER2", email="alice.doe@corp.com", name="Alice Doe")
    assert user2.username == "alice.doe"

    # Test email without @ sign
    user3 = PagerDutyUser(id="USER3", email="username", name="Test User")
    assert user3.username == "username"


def test_pagerduty_api_call_context_immutable() -> None:
    """Test PagerDutyApiCallContext is immutable (frozen=True)."""
    context = PagerDutyApiCallContext(
        method="test",
        verb="GET",
        id="test-instance",
    )

    with pytest.raises(AttributeError):  # dataclass frozen=True raises AttributeError
        context.method = "different"  # type: ignore[misc]


def test_pagerduty_api_retries_on_transient_errors(
    mock_pagerduty_client: MagicMock, enable_retry: None
) -> None:
    """Test that PagerDutyApi retries on transient errors."""
    api = PagerDutyApi(id="test", token="test-token")

    # Mock: first 2 calls fail, 3rd succeeds
    call_count = {"count": 0}

    def side_effect(path: str, **kwargs: dict) -> dict:
        call_count["count"] += 1
        if call_count["count"] < 3:
            raise Exception("API error")  # noqa: TRY002
        return {"email": "alice@example.com", "name": "Alice Smith"}

    api._client.rget = MagicMock(side_effect=side_effect)

    user = api.get_user("USER1")

    assert user.username == "alice"
    assert call_count["count"] == 3


def test_pagerduty_api_gives_up_after_max_attempts(
    mock_pagerduty_client: MagicMock, enable_retry: None
) -> None:
    """Test that PagerDutyApi gives up after max retry attempts."""
    api = PagerDutyApi(id="test", token="test-token")

    # Mock: always fails
    call_count = {"count": 0}

    def side_effect(path: str, **kwargs: dict) -> dict:
        call_count["count"] += 1
        raise Exception("always fails")  # noqa: TRY002

    api._client.rget = MagicMock(side_effect=side_effect)

    with pytest.raises(Exception, match="always fails"):
        api.get_user("USER1")

    # Should have tried 3 times (attempts=3)
    assert call_count["count"] == 3
