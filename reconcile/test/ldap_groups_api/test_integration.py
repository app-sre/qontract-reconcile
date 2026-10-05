"""Tests for ldap-groups-api client integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Callable

import pytest
from qontract_api_client.schemas import (
    LdapGroupsTaskResponse,
    LdapGroupsTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.ldap_groups_api.integration import LdapGroupsApiIntegrationParams
from reconcile.test.ldap_groups_api.conftest import _MOD, _TestableIntegration


def make_integration() -> _TestableIntegration:
    return _TestableIntegration(
        LdapGroupsApiIntegrationParams(aws_sso_namespace="it-cloud-aws")
    )


def _task_response() -> LdapGroupsTaskResponse:
    return LdapGroupsTaskResponse(
        id="task-1",
        status=TaskStatus.SUCCESS,
        status_url="/status/1",
    )


def _task_result(
    *,
    errors: list[str] | None = None,
    updated_managed_groups: list[str] | None = None,
    status: TaskStatus = TaskStatus.SUCCESS,
) -> LdapGroupsTaskResult:
    return LdapGroupsTaskResult(
        status=status,
        errors=errors or [],
        updated_managed_groups=updated_managed_groups or [],
    )


@pytest.mark.asyncio
async def test_persists_managed_groups_before_raising_on_errors() -> None:
    integration = make_integration()
    state_obj: dict[str, list[str]] = {"managed_groups": ["old-group"]}
    mock_state = MagicMock()
    mock_state.__getitem__ = lambda _self, key: state_obj[key]
    mock_state.__setitem__ = lambda _self, key, value: state_obj.__setitem__(key, value)

    settings = MagicMock()
    settings.contact_list = "a@b.com"
    settings.credentials.path = "path"
    settings.credentials.field = None
    settings.credentials.version = None

    secret = {
        "api_url": "https://groups.example.com",
        "issuer_url": "https://sso.example.com",
        "client_id": "cid",
        "client_secret": "secret",
    }

    task_result = _task_result(
        status=TaskStatus.FAILED,
        errors=["failed to update group g2"],
        updated_managed_groups=["g1", "g2"],
    )

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
        pytest.raises(IntegrationError, match="1 error"),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock_state,
            roles=[],
            settings=settings,
            secret=secret,
        )

    assert state_obj["managed_groups"] == ["g1", "g2"]


@pytest.mark.asyncio
async def test_happy_path_persists_managed_groups() -> None:
    integration = make_integration()
    state_obj: dict[str, list[str]] = {}
    mock_state = MagicMock()
    mock_state.__getitem__ = lambda _self, key: state_obj[key]
    mock_state.__setitem__ = lambda _self, key, value: state_obj.__setitem__(key, value)

    settings = MagicMock()
    settings.contact_list = "a@b.com"
    settings.credentials.path = "path"
    settings.credentials.field = None
    settings.credentials.version = None
    secret = {
        "api_url": "https://groups.example.com",
        "issuer_url": "https://sso.example.com",
        "client_id": "cid",
        "client_secret": "secret",
    }

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(
                return_value=_task_result(updated_managed_groups=["group-a"])
            ),
        ),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock_state,
            roles=[],
            settings=settings,
            secret=secret,
        )

    assert state_obj["managed_groups"] == ["group-a"]


@pytest.mark.asyncio
async def test_dry_run_does_not_persist_state_on_success() -> None:
    integration = make_integration()
    state_obj: dict[str, list[str]] = {"managed_groups": ["keep"]}
    mock_state = MagicMock()
    mock_state.__getitem__ = lambda _self, key: state_obj[key]
    mock_state.__setitem__ = MagicMock()
    mock_state.cleanup = MagicMock()

    settings = MagicMock()
    settings.contact_list = "a@b.com"
    settings.credentials.path = "path"
    settings.credentials.field = None
    settings.credentials.version = None

    secret = {
        "api_url": "https://groups.example.com",
        "issuer_url": "https://sso.example.com",
        "client_id": "cid",
        "client_secret": "secret",
    }

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=_task_result(updated_managed_groups=["new"])),
        ),
    ):
        await integration._run_reconcile(
            dry_run=True,
            state_obj=mock_state,
            roles=[],
            settings=settings,
            secret=secret,
        )

    mock_state.__setitem__.assert_not_called()
    assert state_obj["managed_groups"] == ["keep"]


@pytest.mark.asyncio
async def test_async_run_returns_early_when_no_roles() -> None:
    integration = make_integration()
    with (
        patch(f"{_MOD}.gql.get_api"),
        patch(f"{_MOD}.get_roles", return_value=[]),
        patch(f"{_MOD}.init_state") as mock_state,
    ):
        await integration.async_run(dry_run=True)
        mock_state.assert_not_called()


@pytest.mark.asyncio
async def test_raises_on_task_timeout() -> None:
    integration = make_integration()
    mock_state = MagicMock()
    mock_state.cleanup = MagicMock()
    settings = MagicMock()
    settings.contact_list = "a@b.com"
    settings.credentials.path = "path"
    settings.credentials.field = None
    settings.credentials.version = None
    secret = {
        "api_url": "https://groups.example.com",
        "issuer_url": "https://sso.example.com",
        "client_id": "cid",
        "client_secret": "secret",
    }

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=_task_result(status=TaskStatus.PENDING)),
        ),
        pytest.raises(IntegrationError, match="timeout"),
    ):
        await integration._run_reconcile(
            dry_run=True,
            state_obj=mock_state,
            roles=[],
            settings=settings,
            secret=secret,
        )


@pytest.mark.asyncio
async def test_async_run_invokes_reconcile_when_roles_present(
    gql_class_factory: Callable[..., RoleV1],
) -> None:
    integration = make_integration()
    integration._secret_reader = MagicMock()
    integration._secret_reader.read_all_secret.return_value = {}
    mock_state = MagicMock()
    mock_state.cleanup = MagicMock()
    settings = MagicMock()
    role = gql_class_factory(
        RoleV1,
        {"name": "r1", "ldapGroup": {"name": "g1"}, "users": []},
    )

    with (
        patch(f"{_MOD}.gql.get_api") as mock_gql,
        patch(f"{_MOD}.get_roles", return_value=[role]),
        patch(f"{_MOD}.get_integration_settings", return_value=settings),
        patch(f"{_MOD}.init_state", return_value=mock_state),
        patch.object(integration, "_run_reconcile", new=AsyncMock()) as mock_run,
    ):
        mock_gql.return_value.query = MagicMock()
        await integration.async_run(dry_run=True)

    mock_state.cleanup.assert_called_once()
    mock_run.assert_called_once()


def test_get_early_exit_desired_state(
    gql_class_factory: Callable[..., RoleV1],
) -> None:
    integration = make_integration()
    role = gql_class_factory(
        RoleV1,
        {"name": "r1", "ldapGroup": {"name": "g1"}, "users": []},
    )
    with patch(f"{_MOD}.get_roles", return_value=[role]):
        state = integration.get_early_exit_desired_state(query_func=lambda: None)
    assert state["roles"][0]["name"] == "r1"
