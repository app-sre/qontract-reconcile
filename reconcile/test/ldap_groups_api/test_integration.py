"""Tests for ldap-groups-api client integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    LdapGroupsTaskResponse,
    LdapGroupsTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.ldap_groups_api.integration import (
    LdapGroupsApiIntegration,
    LdapGroupsApiIntegrationParams,
)

_MOD = "reconcile.ldap_groups_api.integration"
SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(LdapGroupsApiIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def make_integration() -> _TestableIntegration:
    return _TestableIntegration(
        LdapGroupsApiIntegrationParams(aws_sso_namespace="it-cloud-aws")
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

    task_response = LdapGroupsTaskResponse(
        id="task-1",
        status=TaskStatus.SUCCESS,
        status_url="/status/1",
    )
    task_result = LdapGroupsTaskResult(
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
            new=AsyncMock(return_value=task_response),
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
