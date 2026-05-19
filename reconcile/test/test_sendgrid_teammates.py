from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest

from reconcile.sendgrid_teammates import (
    SendGridAPIError,
    Teammate,
    act,
    fetch_desired_state,
    raise_if_error,
)


class TestTeammate:
    def test_email_sets_username(self) -> None:
        t = Teammate("alice@redhat.com")
        assert t.username == "alice"
        assert t.email == "alice@redhat.com"

    def test_explicit_username(self) -> None:
        t = Teammate("alice@redhat.com", username="custom")
        assert t.username == "custom"

    def test_pending_with_token(self) -> None:
        t = Teammate("a@b.com", pending_token="tok123")
        assert t.pending is True

    def test_not_pending_without_token(self) -> None:
        t = Teammate("a@b.com")
        assert t.pending is False


class TestFetchDesiredState:
    def test_empty_users(self) -> None:
        assert fetch_desired_state([]) == {}

    def test_users_with_sendgrid_accounts(self) -> None:
        users: list[Mapping[str, Any]] = [
            {
                "org_username": "alice",
                "roles": [
                    {
                        "sendgrid_accounts": [{"name": "acct-1"}],
                    }
                ],
            },
            {
                "org_username": "bob",
                "roles": [
                    {
                        "sendgrid_accounts": [{"name": "acct-1"}],
                    }
                ],
            },
        ]
        result = fetch_desired_state(users)
        assert "acct-1" in result
        assert len(result["acct-1"]) == 2
        emails = {t.email for t in result["acct-1"]}
        assert emails == {"alice@redhat.com", "bob@redhat.com"}

    def test_users_without_roles(self) -> None:
        users: list[Mapping[str, Any]] = [{"org_username": "alice", "roles": None}]
        assert fetch_desired_state(users) == {}


class TestRaiseIfError:
    def test_success_does_not_raise(self) -> None:
        response = MagicMock()
        response.status_code = 200
        raise_if_error(response)

    def test_error_raises(self) -> None:
        response = MagicMock()
        response.status_code = 400
        response.body = b"Bad Request"
        with pytest.raises(SendGridAPIError, match="Bad Request"):
            raise_if_error(response)


class TestAct:
    @staticmethod
    def _mock_response(status_code: int = 200) -> MagicMock:
        r = MagicMock()
        r.status_code = status_code
        return r

    def test_dry_run_no_api_calls(self) -> None:
        sg_client = MagicMock()
        desired = [Teammate("new@redhat.com")]
        current = [Teammate("old@redhat.com", username="old")]
        error = act(
            dry_run=True,
            sg_client=sg_client,
            desired_state=desired,
            current_state=current,
        )
        assert error is False
        sg_client.teammates.post.assert_not_called()

    def test_delete_user(self) -> None:
        sg_client = MagicMock()
        sg_client.teammates._("old").delete.return_value = self._mock_response()
        desired: list[Teammate] = []
        current = [Teammate("old@redhat.com", username="old")]
        error = act(
            dry_run=False,
            sg_client=sg_client,
            desired_state=desired,
            current_state=current,
        )
        assert error is False
        sg_client.teammates._("old").delete.assert_called_once()

    def test_invite_user(self) -> None:
        sg_client = MagicMock()
        sg_client.teammates.post.return_value = self._mock_response()
        desired = [Teammate("new@redhat.com")]
        current: list[Teammate] = []
        error = act(
            dry_run=False,
            sg_client=sg_client,
            desired_state=desired,
            current_state=current,
        )
        assert error is False
        sg_client.teammates.post.assert_called_once()

    def test_no_changes_needed(self) -> None:
        sg_client = MagicMock()
        desired = [Teammate("same@redhat.com")]
        current = [Teammate("same@redhat.com", username="same")]
        error = act(
            dry_run=False,
            sg_client=sg_client,
            desired_state=desired,
            current_state=current,
        )
        assert error is False
        sg_client.teammates.post.assert_not_called()
