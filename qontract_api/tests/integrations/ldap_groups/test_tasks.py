"""Tests for ldap-groups Celery tasks."""

from unittest.mock import MagicMock, patch

from qontract_utils.internal_groups_api.models import Entity, EntityType, Group

from qontract_api.integrations.ldap_groups.schemas import LdapGroupsTaskResult
from qontract_api.integrations.ldap_groups.tasks import (
    generate_lock_key,
    reconcile_ldap_groups_task,
)
from qontract_api.internal_groups.domain import InternalGroupsConnectionSecret
from qontract_api.models import TaskStatus

CONNECTION = InternalGroupsConnectionSecret(
    secret_manager_url="https://vault.example.com",
    path="creds",
    api_url="https://groups.example.com",
    issuer_url="https://sso.example.com",
    client_id="client-id",
)


def _group() -> Group:
    owner = Entity(type=EntityType.SERVICE_ACCOUNT, id="sa-1")
    return Group(
        name="group-a",
        description="desc",
        contact_list="a@example.com",
        owners=[owner],
        display_name="group-a",
    )


def test_generate_lock_key() -> None:
    key = generate_lock_key(MagicMock(), CONNECTION)
    assert key == "ldap-groups:https://groups.example.com:client-id"


def test_generate_lock_key_ignores_extra_task_args() -> None:
    key = generate_lock_key(MagicMock(), CONNECTION, [_group()], ["g1"], dry_run=False)
    assert key == "ldap-groups:https://groups.example.com:client-id"


@patch("qontract_api.integrations.ldap_groups.tasks.LdapGroupsService")
@patch("qontract_api.integrations.ldap_groups.tasks.get_secret_manager")
@patch("qontract_api.integrations.ldap_groups.tasks.get_cache")
def test_reconcile_task_returns_service_result(
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    expected = LdapGroupsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        errors=[],
        updated_managed_groups=["group-a"],
    )
    mock_service_cls.return_value.reconcile.return_value = expected

    result = reconcile_ldap_groups_task.run(
        CONNECTION,
        [_group()],
        ["group-a"],
        dry_run=True,
    )

    assert result == expected
    mock_service_cls.return_value.reconcile.assert_called_once_with(
        connection=CONNECTION,
        desired_groups=[_group()],
        managed_group_names=["group-a"],
        dry_run=True,
    )


@patch("qontract_api.integrations.ldap_groups.tasks.LdapGroupsService")
@patch("qontract_api.integrations.ldap_groups.tasks.get_secret_manager")
@patch("qontract_api.integrations.ldap_groups.tasks.get_cache")
def test_reconcile_task_unexpected_error_returns_failed(
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_service_cls: MagicMock,
) -> None:
    mock_service_cls.return_value.reconcile.side_effect = RuntimeError("boom")

    result = reconcile_ldap_groups_task.run(
        CONNECTION,
        [],
        ["z-group", "a-group"],
        dry_run=True,
    )

    assert result.status == TaskStatus.FAILED
    assert result.errors == ["Unexpected err=RuntimeError('boom')"]
    assert result.updated_managed_groups == ["a-group", "z-group"]
