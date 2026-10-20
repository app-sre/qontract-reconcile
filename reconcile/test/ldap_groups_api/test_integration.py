"""Tests for ldap-groups-api client integration."""

from __future__ import annotations

import asyncio
import io
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Callable

import pytest
from botocore.exceptions import ClientError
from qontract_api_client.schemas import (
    LdapGroupsTaskResponse,
    LdapGroupsTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.ldap_groups_api.integration import (
    LdapGroupsApiIntegration,
    LdapGroupsApiIntegrationParams,
)
from reconcile.test.ldap_groups_api.conftest import (
    _MOD,
    SECRET_MANAGER_URL,
    _TestableIntegration,
)


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
    applied_count: int = 0,
) -> LdapGroupsTaskResult:
    return LdapGroupsTaskResult(
        status=status,
        errors=errors or [],
        updated_managed_groups=updated_managed_groups,
        applied_count=applied_count,
    )


def _no_such_key_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}},
        "GetObject",
    )


def _mock_state(
    state_obj: dict[str, Any] | None = None,
    *,
    legacy_groups: list[str] | None = None,
) -> MagicMock:
    """Build a mock State with optional legacy S3 fallback."""
    data: dict[str, Any] = state_obj if state_obj is not None else {}
    s3_objects: dict[str, bytes] = {}
    put_calls: list[dict[str, Any]] = []
    mock = MagicMock()
    mock.data = data
    mock.put_calls = put_calls

    def _getitem(_self: MagicMock, key: str) -> Any:
        return data[key]

    def _setitem(_self: MagicMock, key: str, value: Any) -> None:
        data[key] = value

    mock.__getitem__ = _getitem
    mock.__setitem__ = _setitem
    mock.bucket = "test-bucket"
    mock.exists = lambda key: key in data

    def _rm(key: str) -> None:
        del data[key]

    mock.rm = _rm

    def _put_object(**kwargs: Any) -> None:
        put_calls.append(kwargs)
        body = kwargs["Body"]
        if isinstance(body, str):
            body = body.encode()
        s3_objects[kwargs["Key"]] = body

    def _get_object(Bucket: str, Key: str) -> dict:  # ruff: ignore[invalid-argument-name]
        if Key in s3_objects:
            return {"Body": io.BytesIO(s3_objects[Key])}
        if Key.endswith("managed_groups") and legacy_groups is not None:
            body = io.BytesIO(json.dumps(legacy_groups).encode())
            return {"Body": body}
        raise _no_such_key_error()

    mock.client.put_object.side_effect = _put_object
    mock.client.get_object.side_effect = _get_object
    return mock


_SECRET = {
    "api_url": "https://groups.example.com",
    "issuer_url": "https://sso.example.com",
    "client_id": "cid",
    "client_secret": "secret",
}


def _settings() -> MagicMock:
    s = MagicMock()
    s.contact_list = "a@b.com"
    s.credentials.path = "path"
    s.credentials.field = None
    s.credentials.version = None
    return s


@pytest.mark.asyncio
async def test_persists_managed_groups_before_raising_on_errors() -> None:
    integration = make_integration()
    state_data: dict[str, list[str]] = {"managed_groups": ["old-group"]}
    mock = _mock_state(state_data)

    task_result = _task_result(
        status=TaskStatus.FAILED,
        errors=["failed to update group g2"],
        updated_managed_groups=["g1", "g2"],
    )

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert state_data["managed_groups"] == ["g1", "g2"]


@pytest.mark.asyncio
async def test_happy_path_persists_managed_groups() -> None:
    integration = make_integration()
    state_data: dict[str, list[str]] = {}
    mock = _mock_state(state_data)

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert state_data["managed_groups"] == ["group-a"]


@pytest.mark.asyncio
async def test_dry_run_does_not_persist_state_on_success() -> None:
    integration = make_integration()
    state_data: dict[str, list[str]] = {"managed_groups": ["keep"]}
    mock = _mock_state(state_data)
    mock.__setitem__ = MagicMock()
    mock.cleanup = MagicMock()

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    mock.__setitem__.assert_not_called()
    assert state_data["managed_groups"] == ["keep"]


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
    mock = _mock_state({"managed_groups": []})
    mock.cleanup = MagicMock()

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )


@pytest.mark.asyncio
async def test_polling_failure_preserves_bookmark() -> None:
    integration = make_integration()
    state_data: dict[str, list[str]] = {"managed_groups": ["existing-group"]}
    mock = _mock_state(state_data)

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(side_effect=ConnectionError("network down")),
        ),
        pytest.raises(ConnectionError, match="network down"),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert state_data["managed_groups"] == ["existing-group"]


@pytest.mark.asyncio
async def test_legacy_state_fallback_for_cutover() -> None:
    integration = make_integration()
    state_data: dict[str, list[str]] = {}
    mock = _mock_state(state_data, legacy_groups=["legacy-g1", "legacy-g2"])

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(
                return_value=_task_result(
                    updated_managed_groups=["legacy-g1", "legacy-g2"]
                )
            ),
        ),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    call_args = mock_reconcile.call_args
    request = call_args[0][0]
    assert request.managed_group_names == ["legacy-g1", "legacy-g2"]
    assert state_data["managed_groups"] == ["legacy-g1", "legacy-g2"]


@pytest.mark.asyncio
async def test_managed_names_exclude_desired_names() -> None:
    from qontract_utils.internal_groups_api.models import Entity, EntityType, Group

    integration = make_integration()
    state_data: dict[str, list[str]] = {"managed_groups": ["existing"]}
    mock = _mock_state(state_data)

    desired_group = Group(
        name="new-desired",
        description="test",
        display_name="new-desired",
        contact_list="x@y.com",
        owners=[Entity(type=EntityType.USER, id="u1")],
    )

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[desired_group]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(
                return_value=_task_result(
                    updated_managed_groups=["existing", "new-desired"]
                )
            ),
        ),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    call_args = mock_reconcile.call_args
    request = call_args[0][0]
    assert request.managed_group_names == ["existing"]


@pytest.mark.asyncio
async def test_async_run_invokes_reconcile_when_roles_present(
    gql_class_factory: Callable[..., RoleV1],
) -> None:
    integration = make_integration()
    integration._secret_reader = MagicMock()
    integration._secret_reader.read_all_secret.return_value = {}
    mock = MagicMock()
    mock.cleanup = MagicMock()
    settings = MagicMock()
    role = gql_class_factory(
        RoleV1,
        {"name": "r1", "ldapGroup": {"name": "g1"}, "users": []},
    )

    with (
        patch(f"{_MOD}.gql.get_api") as mock_gql,
        patch(f"{_MOD}.get_roles", return_value=[role]),
        patch(f"{_MOD}.get_integration_settings", return_value=settings),
        patch(f"{_MOD}.init_state", return_value=mock),
        patch.object(integration, "_run_reconcile", new=AsyncMock()) as mock_run,
    ):
        mock_gql.return_value.query = MagicMock()
        await integration.async_run(dry_run=True)

    mock.cleanup.assert_called_once()
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


def test_persist_writes_both_keys() -> None:
    mock = _mock_state({})
    LdapGroupsApiIntegration._persist_managed_groups(mock, ["g1", "g2"])
    assert mock.data["managed_groups"] == ["g1", "g2"]
    legacy_puts = [
        c for c in mock.put_calls if c["Key"].endswith("ldap-groups/managed_groups")
    ]
    assert len(legacy_puts) == 1
    assert json.loads(legacy_puts[0]["Body"]) == ["g1", "g2"]


def test_load_reraises_non_nosuchkey() -> None:
    mock = _mock_state({})
    mock.client.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
        "GetObject",
    )
    with pytest.raises(ClientError):
        LdapGroupsApiIntegration._load_managed_groups(mock)


@pytest.mark.asyncio
async def test_synthetic_empty_bookmark_not_persisted() -> None:
    integration = make_integration()
    state_data: dict[str, Any] = {"managed_groups": ["previously-managed"]}
    mock = _mock_state(state_data)
    task_result = _task_result(
        status=TaskStatus.SUCCESS,
        errors=["Task skipped: duplicate"],
        updated_managed_groups=None,
    )

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
        pytest.raises(IntegrationError, match="Task skipped"),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert state_data["managed_groups"] == ["previously-managed"]
    assert not mock.put_calls


@pytest.mark.asyncio
async def test_confirmed_empty_bookmark_persisted() -> None:
    integration = make_integration()
    state_data: dict[str, Any] = {"managed_groups": ["previously-managed"]}
    mock = _mock_state(state_data)
    task_result = _task_result(
        status=TaskStatus.SUCCESS,
        updated_managed_groups=[],
    )

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert state_data["managed_groups"] == []


@pytest.mark.asyncio
async def test_synthetic_empty_bookmark_not_persisted_on_failed() -> None:
    integration = make_integration()
    state_data: dict[str, Any] = {"managed_groups": ["previously-managed"]}
    mock = _mock_state(state_data)
    task_result = _task_result(
        status=TaskStatus.FAILED,
        errors=["Worker lost"],
        updated_managed_groups=None,
    )

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
        pytest.raises(IntegrationError, match="Worker lost"),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert state_data["managed_groups"] == ["previously-managed"]
    assert not mock.put_calls


@pytest.mark.asyncio
async def test_pending_task_persisted_before_poll() -> None:
    integration = make_integration()
    mock = _mock_state({})

    async def _poll_with_pending_check(
        *_args: object, **_kwargs: object
    ) -> LdapGroupsTaskResult:
        await asyncio.sleep(0)
        assert "pending_task" in mock.data
        assert mock.data["pending_task"]["id"] == "task-1"
        return _task_result(updated_managed_groups=["g1"])

    poll = AsyncMock(side_effect=_poll_with_pending_check)

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(integration, "poll_task_status", new=poll),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert "pending_task" not in mock.data
    poll.assert_awaited_once()


@pytest.mark.asyncio
async def test_polling_failure_keeps_pending_task() -> None:
    integration = make_integration()
    state_data: dict[str, Any] = {"managed_groups": ["existing-group"]}
    mock = _mock_state(state_data)

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(side_effect=ConnectionError("network down")),
        ),
        pytest.raises(ConnectionError, match="network down"),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert mock.data["pending_task"]["status_url"] == "/status/1"
    assert state_data["managed_groups"] == ["existing-group"]


@pytest.mark.asyncio
async def test_recover_pending_task() -> None:
    integration = make_integration()
    state_data: dict[str, Any] = {
        "managed_groups": ["old"],
        "pending_task": {"id": "task-1", "status_url": "/status/1"},
    }
    mock = _mock_state(state_data)
    poll = AsyncMock(
        return_value=_task_result(updated_managed_groups=["old", "recovered"])
    )

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(integration, "poll_task_status", new=poll),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    assert state_data["managed_groups"] == ["old", "recovered"]
    assert "pending_task" not in state_data
    assert poll.await_count == 2


@pytest.mark.asyncio
async def test_rollback_legacy_reads_api_state() -> None:
    integration = make_integration()
    mock = _mock_state({})

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
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
                return_value=_task_result(updated_managed_groups=["api-created"])
            ),
        ),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    legacy_mock = _mock_state({})
    legacy_mock.client.get_object = mock.client.get_object
    legacy_mock.bucket = mock.bucket
    with pytest.raises(KeyError):
        legacy_mock["managed_groups"]
    assert json.loads(
        legacy_mock.client.get_object(
            Bucket=legacy_mock.bucket,
            Key="state/ldap-groups/managed_groups",
        )["Body"].read()
    ) == ["api-created"]


@pytest.mark.asyncio
async def test_ldap_member_source_passes_settings(
    gql_class_factory: Callable[..., RoleV1],
) -> None:
    integration = make_integration()
    role = gql_class_factory(
        RoleV1,
        {"name": "r1", "ldapGroup": {"name": "g1"}, "users": []},
    )
    ldap_settings = MagicMock()
    resolve_mock = AsyncMock(return_value=[role])

    with (
        patch(f"{_MOD}.has_ldap_sources", return_value=True),
        patch(f"{_MOD}.get_ldap_settings", return_value=ldap_settings),
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=resolve_mock),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=_task_result()),
        ),
    ):
        await integration._run_reconcile(
            dry_run=True,
            state_obj=_mock_state({}),
            roles=[role],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    resolve_mock.assert_awaited_once()
    assert resolve_mock.await_args is not None
    kwargs = resolve_mock.await_args.kwargs
    assert kwargs["ldap_settings"] is ldap_settings
    assert kwargs["secret_manager_url"] == SECRET_MANAGER_URL


@pytest.mark.asyncio
async def test_no_ldap_settings_when_no_ldap_sources(
    gql_class_factory: Callable[..., RoleV1],
) -> None:
    integration = make_integration()
    role = gql_class_factory(
        RoleV1,
        {"name": "r1", "ldapGroup": {"name": "g1"}, "users": []},
    )
    resolve_mock = AsyncMock(return_value=[role])

    with (
        patch(f"{_MOD}.has_ldap_sources", return_value=False),
        patch(f"{_MOD}.get_ldap_settings") as mock_get_ldap,
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=resolve_mock),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=_task_result()),
        ),
    ):
        await integration._run_reconcile(
            dry_run=True,
            state_obj=_mock_state({}),
            roles=[role],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    mock_get_ldap.assert_not_called()
    assert resolve_mock.await_args is not None
    assert resolve_mock.await_args.kwargs["ldap_settings"] is None
    assert resolve_mock.await_args.kwargs["secret_manager_url"] is None


@pytest.mark.asyncio
async def test_delayed_completion_desired_removal() -> None:
    integration = make_integration()
    state_data: dict[str, Any] = {
        "managed_groups": [],
        "pending_task": {"id": "task-1", "status_url": "/status/1"},
    }
    mock = _mock_state(state_data)
    poll_results = [
        _task_result(updated_managed_groups=["orphan-group"]),
        _task_result(updated_managed_groups=["orphan-group"]),
    ]
    poll = AsyncMock(side_effect=poll_results)

    with (
        patch(f"{_MOD}.validate_no_circular_memberships"),
        patch(f"{_MOD}.resolve_role_members", new=AsyncMock(return_value=[])),
        patch(f"{_MOD}.get_desired_groups_for_roles", return_value=[]),
        patch(f"{_MOD}.get_desired_groups_for_aws_roles", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ldap_groups",
            new=AsyncMock(return_value=_task_response()),
        ) as mock_reconcile,
        patch.object(integration, "poll_task_status", new=poll),
    ):
        await integration._run_reconcile(
            dry_run=False,
            state_obj=mock,
            roles=[],
            settings=_settings(),
            secret=_SECRET,
            query_func=MagicMock(),
        )

    request = mock_reconcile.call_args[0][0]
    assert request.managed_group_names == ["orphan-group"]
    assert "pending_task" not in state_data
