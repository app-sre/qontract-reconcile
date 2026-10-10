"""Unit tests for LdapGroupsService."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.internal_groups_api.models import Entity, EntityType, Group

from qontract_api.integrations.ldap_groups.metrics import (
    INTEGRATION_NAME,
    ldap_groups_reconcile_errors,
    ldap_groups_reconciled,
)
from qontract_api.integrations.ldap_groups.service import LdapGroupsService
from qontract_api.internal_groups.domain import InternalGroupsConnectionSecret
from qontract_api.models import TaskStatus

CONNECTION = InternalGroupsConnectionSecret(
    secret_manager_url="https://vault.example.com",
    path="ldap-groups/creds",
    api_url="https://groups.example.com",
    issuer_url="https://sso.example.com",
    client_id="client-id",
)


def _group(
    name: str = "group-a",
    *,
    members: list[Entity] | None = None,
    notes: str | None = None,
) -> Group:
    owner = Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")
    return Group(
        name=name,
        description="desc",
        contact_list="a@example.com",
        owners=[owner],
        display_name=name,
        members=members
        if members is not None
        else [Entity(type=EntityType.USER, id="user-1")],
        notes=notes,
    )


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    client = MagicMock()
    client.get_group.return_value = None
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


@pytest.fixture(autouse=True)
def patch_workspace_factory(
    mock_workspace_client: MagicMock,
) -> Generator[MagicMock]:
    with patch(
        "qontract_api.integrations.ldap_groups.service.create_internal_groups_workspace_client",
        return_value=mock_workspace_client,
    ):
        yield mock_workspace_client


@pytest.fixture
def service() -> LdapGroupsService:
    return LdapGroupsService(
        cache=MagicMock(),
        secret_manager=MagicMock(),
        settings=MagicMock(),
    )


def test_reconcile_dry_run_create_action(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    desired = [_group()]
    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=desired,
        managed_group_names=[],
        dry_run=True,
    )
    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.actions[0].action_type == "create_ldap_group"
    assert result.updated_managed_groups == []
    mock_workspace_client.create_group.assert_not_called()


def test_reconcile_applies_create(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    desired = [_group()]
    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=desired,
        managed_group_names=[],
        dry_run=False,
    )
    assert result.status == TaskStatus.SUCCESS
    mock_workspace_client.create_group.assert_called_once()
    assert result.updated_managed_groups == ["group-a"]


def test_reconcile_dry_run_delete_and_update(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    current = _group(members=[Entity(type=EntityType.USER, id="user-old")])
    desired = _group(members=[Entity(type=EntityType.USER, id="user-new")])
    mock_workspace_client.get_group.return_value = current

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[desired],
        managed_group_names=["group-a"],
        dry_run=True,
    )

    assert result.status == TaskStatus.SUCCESS
    assert {a.action_type for a in result.actions} == {"update_ldap_group"}
    mock_workspace_client.delete_group.assert_not_called()
    mock_workspace_client.update_group.assert_not_called()


def test_reconcile_applies_update(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    current = _group(members=[Entity(type=EntityType.USER, id="user-old")])
    desired = _group(
        members=[Entity(type=EntityType.USER, id="user-new")],
        notes="updated",
    )
    mock_workspace_client.get_group.return_value = current

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[desired],
        managed_group_names=["group-a"],
        dry_run=False,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions[0].action_type == "update_ldap_group"
    assert result.actions[0].notes == "updated"
    mock_workspace_client.update_group.assert_called_once_with(desired)
    assert result.updated_managed_groups == ["group-a"]


def test_reconcile_applies_delete(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group.return_value = _group("orphan")

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[],
        managed_group_names=["orphan"],
        dry_run=False,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions[0].action_type == "delete_ldap_group"
    mock_workspace_client.delete_group.assert_called_once_with("orphan")
    assert result.updated_managed_groups == []


def test_reconcile_fetches_managed_names_not_in_desired(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group.return_value = _group("stale")

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[],
        managed_group_names=["stale"],
        dry_run=True,
    )

    mock_workspace_client.get_group.assert_called_once_with("stale")
    assert result.actions[0].action_type == "delete_ldap_group"


def test_reconcile_increments_error_counter_on_failure(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.create_group.side_effect = RuntimeError("create failed")

    before = ldap_groups_reconcile_errors.labels(INTEGRATION_NAME)._value.get()
    reconciled_before = ldap_groups_reconciled.labels(INTEGRATION_NAME)._value.get()

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[_group()],
        managed_group_names=[],
        dry_run=False,
    )

    assert result.status == TaskStatus.FAILED
    assert result.applied_count == 0
    assert "create failed" in result.errors[0]
    assert result.updated_managed_groups == []
    assert (
        ldap_groups_reconcile_errors.labels(INTEGRATION_NAME)._value.get() == before + 1
    )
    assert (
        ldap_groups_reconciled.labels(INTEGRATION_NAME)._value.get()
        == reconciled_before
    )


def test_reconcile_delete_failure(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group.return_value = _group("orphan")
    mock_workspace_client.delete_group.side_effect = RuntimeError("delete failed")

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[],
        managed_group_names=["orphan"],
        dry_run=False,
    )

    assert result.status == TaskStatus.FAILED
    assert "delete failed" in result.errors[0]
    # delete did not complete — name remains in managed set
    assert result.updated_managed_groups == ["orphan"]


def test_reconcile_update_failure(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    current = _group(members=[Entity(type=EntityType.USER, id="user-old")])
    desired = _group(members=[Entity(type=EntityType.USER, id="user-new")])
    mock_workspace_client.get_group.return_value = current
    mock_workspace_client.update_group.side_effect = RuntimeError("update failed")

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[desired],
        managed_group_names=["group-a"],
        dry_run=False,
    )

    assert result.status == TaskStatus.FAILED
    assert "update failed" in result.errors[0]
    assert result.updated_managed_groups == ["group-a"]


def test_reconcile_increments_reconciled_counter_on_success(
    service: LdapGroupsService, mock_workspace_client: MagicMock
) -> None:
    before = ldap_groups_reconciled.labels(INTEGRATION_NAME)._value.get()

    result = service.reconcile(
        connection=CONNECTION,
        desired_groups=[_group()],
        managed_group_names=[],
        dry_run=True,
    )

    assert result.status == TaskStatus.SUCCESS
    assert ldap_groups_reconciled.labels(INTEGRATION_NAME)._value.get() == before + 1
