from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from reconcile.sendgrid_teammates import (
    SendGridAPIError,
    Teammate,
    act,
    fetch_desired_state,
    raise_if_error,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@pytest.fixture
def sg_client() -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.status_code = 200
    client.teammates.post.return_value = response
    client.teammates._().delete.return_value = response
    return client


@pytest.mark.parametrize(
    "email, username, pending_token, expected_username, expected_pending",
    [
        pytest.param(
            "alice@redhat.com", None, None, "alice", False, id="email-derives-username"
        ),
        pytest.param(
            "alice@redhat.com",
            "custom",
            None,
            "custom",
            False,
            id="explicit-username",
        ),
        pytest.param("a@b.com", None, "tok123", "a", True, id="pending-with-token"),
    ],
)
def test_teammate(
    email: str,
    username: str | None,
    pending_token: str | None,
    expected_username: str,
    expected_pending: bool,
) -> None:
    t = Teammate(email, pending_token=pending_token, username=username)
    assert t.email == email
    assert t.username == expected_username
    assert t.pending is expected_pending


def test_fetch_desired_state_empty() -> None:
    assert fetch_desired_state([]) == {}


def test_fetch_desired_state_with_accounts() -> None:
    users: list[Mapping[str, Any]] = [
        {
            "org_username": "alice",
            "roles": [{"sendgrid_accounts": [{"name": "acct-1"}]}],
        },
        {
            "org_username": "bob",
            "roles": [{"sendgrid_accounts": [{"name": "acct-1"}]}],
        },
    ]
    result = fetch_desired_state(users)
    assert "acct-1" in result
    assert len(result["acct-1"]) == 2
    assert {t.email for t in result["acct-1"]} == {
        "alice@redhat.com",
        "bob@redhat.com",
    }


def test_fetch_desired_state_no_roles() -> None:
    users: list[Mapping[str, Any]] = [{"org_username": "alice", "roles": None}]
    assert fetch_desired_state(users) == {}


def test_raise_if_error_success() -> None:
    response = MagicMock()
    response.status_code = 200
    raise_if_error(response)


def test_raise_if_error_failure() -> None:
    response = MagicMock()
    response.status_code = 400
    response.body = b"Bad Request"
    with pytest.raises(SendGridAPIError, match="Bad Request"):
        raise_if_error(response)


def test_act_dry_run(sg_client: MagicMock) -> None:
    error = act(
        dry_run=True,
        sg_client=sg_client,
        desired_state=[Teammate("new@redhat.com")],
        current_state=[Teammate("old@redhat.com", username="old")],
    )
    assert error is False
    sg_client.teammates.post.assert_not_called()


def test_act_delete_user(sg_client: MagicMock) -> None:
    error = act(
        dry_run=False,
        sg_client=sg_client,
        desired_state=[],
        current_state=[Teammate("old@redhat.com", username="old")],
    )
    assert error is False
    sg_client.teammates._("old").delete.assert_called_once()


def test_act_invite_user(sg_client: MagicMock) -> None:
    error = act(
        dry_run=False,
        sg_client=sg_client,
        desired_state=[Teammate("new@redhat.com")],
        current_state=[],
    )
    assert error is False
    sg_client.teammates.post.assert_called_once()


def test_act_no_changes(sg_client: MagicMock) -> None:
    error = act(
        dry_run=False,
        sg_client=sg_client,
        desired_state=[Teammate("same@redhat.com")],
        current_state=[Teammate("same@redhat.com", username="same")],
    )
    assert error is False
    sg_client.teammates.post.assert_not_called()
