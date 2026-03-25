"""Tests for the github-owners-api client-side integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.models.github_org_desired_state import GithubOrgDesiredState
from qontract_api_client.models.github_owner_action_add_owner import (
    GithubOwnerActionAddOwner,
)
from qontract_api_client.models.github_owners_task_response import (
    GithubOwnersTaskResponse,
)
from qontract_api_client.models.github_owners_task_result import GithubOwnersTaskResult
from qontract_api_client.models.secret import Secret
from qontract_api_client.models.task_status import TaskStatus
from qontract_utils.exceptions import IntegrationError

from reconcile.github_owners_api import (
    GithubOwnersIntegration,
    GithubOwnersIntegrationParams,
)
from reconcile.gql_definitions.common.github_orgs import GithubOrgV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.github_owners_api.roles import (
    BotV1,
    PermissionGithubOrgTeamV1,
    PermissionGithubOrgV1,
    PermissionV1,
    RoleV1,
    UserV1,
)

SECRET_MANAGER_URL = "https://vault.example.com"


def make_integration(org_name: str | None = None) -> GithubOwnersIntegration:
    integration = GithubOwnersIntegration(
        GithubOwnersIntegrationParams(org_name=org_name)
    )
    # Patch secret_manager_url to avoid reading config in tests
    type(integration).secret_manager_url = property(lambda self: SECRET_MANAGER_URL)
    return integration


def make_vault_secret(
    path: str = "app-sre/creds/gh", field: str = "token", version: int = 1
) -> VaultSecret:
    return VaultSecret(path=path, field=field, version=version, format=None)


def make_github_org(name: str, vault_path: str = "app-sre/creds/gh") -> GithubOrgV1:
    return GithubOrgV1(
        name=name,
        token=make_vault_secret(path=vault_path),
        default=None,
        managedTeams=None,
    )


def make_role(
    name: str = "test-role",
    users: list[str] | None = None,
    bots: list[str] | None = None,
    permissions: list | None = None,
    expiration_date: str | None = None,
) -> RoleV1:
    return RoleV1(
        name=name,
        users=[UserV1(github_username=u) for u in (users or [])],
        bots=[BotV1(github_username=b) for b in (bots or [])],
        permissions=permissions,
        expirationDate=expiration_date,
    )


def make_github_org_permission(org: str, role: str = "owner") -> PermissionGithubOrgV1:
    return PermissionGithubOrgV1(service="github-org", org=org, role=role)


def make_github_org_team_permission(
    org: str, role: str = "owner"
) -> PermissionGithubOrgTeamV1:
    return PermissionGithubOrgTeamV1(service="github-org-team", org=org, role=role)


# ---------------------------------------------------------------------------
# compile_desired_state
# ---------------------------------------------------------------------------


class TestCompileDesiredState:
    def test_single_org_single_user(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["Alice"],
                permissions=[make_github_org_permission("my-org")],
            )
        ]
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state(roles, github_orgs)

        assert len(result) == 1
        assert result[0].org_name == "my-org"
        assert result[0].owners == ["alice"]

    def test_usernames_are_lowercased_and_sorted(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["Charlie", "Alice", "BOB"],
                permissions=[make_github_org_permission("my-org")],
            )
        ]
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state(roles, github_orgs)

        assert result[0].owners == ["alice", "bob", "charlie"]

    def test_bots_are_included(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                bots=["bot-user"],
                permissions=[make_github_org_permission("my-org")],
            )
        ]
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state(roles, github_orgs)

        assert "bot-user" in result[0].owners
        assert "alice" in result[0].owners

    def test_bot_without_github_username_is_skipped(self) -> None:
        integration = make_integration()
        role = make_role(
            users=["alice"],
            permissions=[make_github_org_permission("my-org")],
        )
        # Add a bot with no github_username
        role.bots.append(BotV1(github_username=None))
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state([role], github_orgs)

        assert result[0].owners == ["alice"]

    def test_github_org_team_permission_counts(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                permissions=[make_github_org_team_permission("my-org")],
            )
        ]
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state(roles, github_orgs)

        assert result[0].owners == ["alice"]

    def test_non_owner_role_is_ignored(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                permissions=[make_github_org_permission("my-org", role="member")],
            )
        ]
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state(roles, github_orgs)

        assert result == []

    def test_non_github_permission_is_ignored(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                permissions=[PermissionV1(service="openshift-rolebinding")],
            )
        ]
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state(roles, github_orgs)

        assert result == []

    def test_org_name_filter_excludes_other_orgs(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                permissions=[
                    make_github_org_permission("org-a"),
                    make_github_org_permission("org-b"),
                ],
            )
        ]
        github_orgs = {
            "org-a": make_github_org("org-a"),
            "org-b": make_github_org("org-b"),
        }

        result = integration.compile_desired_state(
            roles, github_orgs, org_name_filter="org-a"
        )

        assert len(result) == 1
        assert result[0].org_name == "org-a"

    def test_unknown_org_is_skipped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                permissions=[make_github_org_permission("unknown-org")],
            )
        ]

        result = integration.compile_desired_state(roles, github_orgs={})

        assert result == []
        assert "unknown-org" in caplog.text

    def test_vault_secret_is_mapped_correctly(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                permissions=[make_github_org_permission("my-org")],
            )
        ]
        github_orgs = {
            "my-org": make_github_org("my-org", vault_path="app-sre/creds/my-org-gh")
        }

        result = integration.compile_desired_state(roles, github_orgs)

        token = result[0].token
        assert token.secret_manager_url == SECRET_MANAGER_URL
        assert token.path == "app-sre/creds/my-org-gh"
        assert token.field == "token"

    def test_multiple_roles_aggregated_per_org(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                name="role-a",
                users=["alice"],
                permissions=[make_github_org_permission("my-org")],
            ),
            make_role(
                name="role-b",
                users=["bob"],
                permissions=[make_github_org_permission("my-org")],
            ),
        ]
        github_orgs = {"my-org": make_github_org("my-org")}

        result = integration.compile_desired_state(roles, github_orgs)

        assert len(result) == 1
        assert sorted(result[0].owners) == ["alice", "bob"]

    def test_multiple_orgs_produce_separate_entries(self) -> None:
        integration = make_integration()
        roles = [
            make_role(
                users=["alice"],
                permissions=[
                    make_github_org_permission("org-a"),
                    make_github_org_permission("org-b"),
                ],
            )
        ]
        github_orgs = {
            "org-a": make_github_org("org-a"),
            "org-b": make_github_org("org-b"),
        }

        result = integration.compile_desired_state(roles, github_orgs)

        org_names = {r.org_name for r in result}
        assert org_names == {"org-a", "org-b"}


# ---------------------------------------------------------------------------
# get_roles / get_github_orgs
# ---------------------------------------------------------------------------


class TestGetRoles:
    def test_expired_roles_are_filtered(self) -> None:
        mock_query = MagicMock(
            return_value={
                "roles": [
                    {
                        "name": "active",
                        "users": [],
                        "bots": [],
                        "permissions": [],
                        "expirationDate": None,
                    },
                    {
                        "name": "expired",
                        "users": [],
                        "bots": [],
                        "permissions": [],
                        "expirationDate": "2020-01-01",
                    },
                ]
            }
        )

        result = GithubOwnersIntegration.get_roles(mock_query)

        assert len(result) == 1
        assert result[0].name == "active"

    def test_empty_roles_returns_empty_list(self) -> None:
        mock_query = MagicMock(return_value={"roles": []})
        result = GithubOwnersIntegration.get_roles(mock_query)
        assert result == []


class TestGetGithubOrgs:
    def test_orgs_keyed_by_name(self) -> None:
        mock_query = MagicMock(
            return_value={
                "orgs": [
                    {
                        "name": "org-a",
                        "token": {
                            "path": "p",
                            "field": "f",
                            "version": 1,
                            "format": None,
                        },
                        "default": None,
                        "managedTeams": None,
                    },
                    {
                        "name": "org-b",
                        "token": {
                            "path": "p",
                            "field": "f",
                            "version": 1,
                            "format": None,
                        },
                        "default": None,
                        "managedTeams": None,
                    },
                ]
            }
        )

        result = GithubOwnersIntegration.get_github_orgs(mock_query)

        assert set(result.keys()) == {"org-a", "org-b"}

    def test_empty_orgs_returns_empty_dict(self) -> None:
        mock_query = MagicMock(return_value={"orgs": []})
        result = GithubOwnersIntegration.get_github_orgs(mock_query)
        assert result == {}


# ---------------------------------------------------------------------------
# async_run
# ---------------------------------------------------------------------------


class TestAsyncRun:
    def _make_task_response(
        self, task_id: str = "task-123"
    ) -> GithubOwnersTaskResponse:
        return GithubOwnersTaskResponse(
            id=task_id, status=TaskStatus.PENDING, status_url=f"/tasks/{task_id}"
        )

    def _make_task_result(
        self,
        status: TaskStatus = TaskStatus.SUCCESS,
        actions: list | None = None,
        errors: list | None = None,
    ) -> GithubOwnersTaskResult:
        return GithubOwnersTaskResult(
            status=status,
            actions=actions or [],
            errors=errors or [],
        )

    @pytest.mark.asyncio
    async def test_no_desired_state_exits_early(self) -> None:
        integration = make_integration()

        with (
            patch("reconcile.github_owners_api.gql") as mock_gql,
            patch.object(integration, "compile_desired_state", return_value=[]),
            patch.object(GithubOwnersIntegration, "get_roles", return_value=[]),
            patch.object(GithubOwnersIntegration, "get_github_orgs", return_value={}),
            patch(
                "reconcile.github_owners_api.reconcile_github_owners"
            ) as mock_reconcile,
        ):
            mock_gql.get_api.return_value = MagicMock()
            await integration.async_run(dry_run=True)
            mock_reconcile.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_waits_for_task_and_logs_actions(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()
        action = GithubOwnerActionAddOwner(
            action_type="add_owner", org_name="my-org", username="alice"
        )
        task_result = self._make_task_result(actions=[action])

        desired = [
            GithubOrgDesiredState(
                org_name="my-org",
                owners=["alice"],
                token=Secret(
                    secret_manager_url=SECRET_MANAGER_URL,
                    path="p",
                    field="f",
                    version=1,
                ),
            )
        ]

        with (
            patch("reconcile.github_owners_api.gql") as mock_gql,
            patch.object(GithubOwnersIntegration, "get_roles", return_value=[]),
            patch.object(GithubOwnersIntegration, "get_github_orgs", return_value={}),
            patch.object(integration, "compile_desired_state", return_value=desired),
            patch(
                "reconcile.github_owners_api.reconcile_github_owners",
                new=AsyncMock(return_value=task_response),
            ),
            patch(
                "reconcile.github_owners_api.github_owners_task_status",
                new=AsyncMock(return_value=task_result),
            ),
            patch.object(
                type(integration),
                "qontract_api_client",
                new_callable=lambda: property(lambda self: MagicMock()),
            ),
        ):
            mock_gql.get_api.return_value = MagicMock()
            await integration.async_run(dry_run=True)

    @pytest.mark.asyncio
    async def test_non_dry_run_does_not_wait_for_task(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()

        desired = [
            GithubOrgDesiredState(
                org_name="my-org",
                owners=["alice"],
                token=Secret(
                    secret_manager_url=SECRET_MANAGER_URL,
                    path="p",
                    field="f",
                    version=1,
                ),
            )
        ]

        with (
            patch("reconcile.github_owners_api.gql") as mock_gql,
            patch.object(GithubOwnersIntegration, "get_roles", return_value=[]),
            patch.object(GithubOwnersIntegration, "get_github_orgs", return_value={}),
            patch.object(integration, "compile_desired_state", return_value=desired),
            patch(
                "reconcile.github_owners_api.reconcile_github_owners",
                new=AsyncMock(return_value=task_response),
            ),
            patch(
                "reconcile.github_owners_api.github_owners_task_status"
            ) as mock_status,
            patch.object(
                type(integration),
                "qontract_api_client",
                new_callable=lambda: property(lambda self: MagicMock()),
            ),
        ):
            mock_gql.get_api.return_value = MagicMock()
            await integration.async_run(dry_run=False)
            mock_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_exits_with_errors(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()
        task_result = self._make_task_result(errors=["something went wrong"])

        desired = [
            GithubOrgDesiredState(
                org_name="my-org",
                owners=["alice"],
                token=Secret(
                    secret_manager_url=SECRET_MANAGER_URL,
                    path="p",
                    field="f",
                    version=1,
                ),
            )
        ]

        with (
            patch("reconcile.github_owners_api.gql") as mock_gql,
            patch.object(GithubOwnersIntegration, "get_roles", return_value=[]),
            patch.object(GithubOwnersIntegration, "get_github_orgs", return_value={}),
            patch.object(integration, "compile_desired_state", return_value=desired),
            patch(
                "reconcile.github_owners_api.reconcile_github_owners",
                new=AsyncMock(return_value=task_response),
            ),
            patch(
                "reconcile.github_owners_api.github_owners_task_status",
                new=AsyncMock(return_value=task_result),
            ),
            patch.object(
                type(integration),
                "qontract_api_client",
                new_callable=lambda: property(lambda self: MagicMock()),
            ),
            pytest.raises(IntegrationError),
        ):
            mock_gql.get_api.return_value = MagicMock()
            await integration.async_run(dry_run=True)

    @pytest.mark.asyncio
    async def test_dry_run_exits_on_timeout(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()
        task_result = self._make_task_result(status=TaskStatus.PENDING)

        desired = [
            GithubOrgDesiredState(
                org_name="my-org",
                owners=["alice"],
                token=Secret(
                    secret_manager_url=SECRET_MANAGER_URL,
                    path="p",
                    field="f",
                    version=1,
                ),
            )
        ]

        with (
            patch("reconcile.github_owners_api.gql") as mock_gql,
            patch.object(GithubOwnersIntegration, "get_roles", return_value=[]),
            patch.object(GithubOwnersIntegration, "get_github_orgs", return_value={}),
            patch.object(integration, "compile_desired_state", return_value=desired),
            patch(
                "reconcile.github_owners_api.reconcile_github_owners",
                new=AsyncMock(return_value=task_response),
            ),
            patch(
                "reconcile.github_owners_api.github_owners_task_status",
                new=AsyncMock(return_value=task_result),
            ),
            patch.object(
                type(integration),
                "qontract_api_client",
                new_callable=lambda: property(lambda self: MagicMock()),
            ),
            pytest.raises(IntegrationError),
        ):
            mock_gql.get_api.return_value = MagicMock()
            await integration.async_run(dry_run=True)
