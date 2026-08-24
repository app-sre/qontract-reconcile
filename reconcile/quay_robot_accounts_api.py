"""Quay robot-account reconciliation via qontract-api.

This is the client-side integration that compiles desired state from
App-Interface and calls qontract-api instead of talking to Quay directly.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict

from qontract_api_client.client import (
    quay_robot_accounts as reconcile_quay_robot_accounts,
)
from qontract_api_client.schemas import (
    QuayOrgDesiredState,
    QuayRobotAccountsReconcileRequest,
    QuayRobotAccountsTaskResponse,
    QuayRobotAccountsTaskResult,
    QuayRobotActionAddTeam,
    QuayRobotActionCreate,
    QuayRobotActionDelete,
    QuayRobotActionRemoveRepoPermission,
    QuayRobotActionRemoveTeam,
    QuayRobotActionSetRepoPermission,
    QuayRobotDesiredState,
    Secret,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.quay_robot_accounts_api.quay_robot_accounts import (
    QuayRobotV1,
)
from reconcile.gql_definitions.quay_robot_accounts_api.quay_robot_accounts import (
    query as robots_query,
)
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


class _OrgMeta(TypedDict):
    instance_name: str
    instance_url: str
    org_name: str
    token: VaultSecret | None
    managed_teams: list[str]
    managed_repos: bool
    managed_robot_accounts: bool


QONTRACT_INTEGRATION = "quay-robot-accounts-api"


class QuayRobotAccountsIntegrationParams(PydanticRunParams):
    """Parameters for quay-robot-accounts-api integration."""

    org_name: str | None = None


class QuayRobotAccountsIntegration(
    QontractReconcileApiIntegration[QuayRobotAccountsIntegrationParams]
):
    """Manage Quay robot accounts via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_robot_accounts(query_func: Callable) -> list[QuayRobotV1]:
        result = robots_query(query_func=query_func)
        return list(result.robot_accounts or [])

    def compile_desired_state(
        self,
        robots: list[QuayRobotV1],
        org_name_filter: str | None = None,
    ) -> list[QuayOrgDesiredState]:
        """Group robots by org and attach org guardrails + token refs."""
        errors: list[str] = []
        buckets: dict[tuple[str, str], _OrgMeta] = {}
        robots_by_org: dict[tuple[str, str], list[QuayRobotDesiredState]] = defaultdict(
            list
        )

        for robot in robots:
            if not robot.quay_org:
                continue
            org = robot.quay_org
            if org_name_filter and org.name != org_name_filter:
                continue

            key = (org.instance.name, org.name)
            if key not in buckets:
                buckets[key] = {
                    "instance_name": org.instance.name,
                    "instance_url": org.instance.url,
                    "org_name": org.name,
                    "token": org.automation_token,
                    "managed_teams": list(org.managed_teams or []),
                    "managed_repos": bool(org.managed_repos),
                    "managed_robot_accounts": bool(org.managed_robot_accounts),
                }

            repositories = {
                repo.name: repo.permission for repo in (robot.repositories or [])
            }
            robots_by_org[key].append(
                QuayRobotDesiredState(
                    name=robot.name,
                    description=robot.description,
                    teams=list(robot.teams or []),
                    repositories=repositories,
                    delete=bool(robot.delete),
                )
            )

        desired: list[QuayOrgDesiredState] = []
        for key, meta in buckets.items():
            token = meta["token"]
            if token is None:
                errors.append(
                    f"{meta['instance_name']}/{meta['org_name']}: no automationToken "
                    "(cannot manage robot accounts)"
                )
                continue
            desired.append(
                QuayOrgDesiredState(
                    instance_name=meta["instance_name"],
                    instance_url=meta["instance_url"],
                    org_name=meta["org_name"],
                    token=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=token.path,
                        field=token.field,
                        version=token.version,
                    ),
                    managed_teams=meta["managed_teams"],
                    managed_repos=meta["managed_repos"],
                    managed_robot_accounts=meta["managed_robot_accounts"],
                    robots=robots_by_org[key],
                )
            )

        if errors:
            summary = "; ".join(errors)
            raise IntegrationError(
                f"quay-robot-accounts-api: {len(errors)} error(s): {summary}"
            )
        return desired

    async def reconcile(
        self,
        organizations: list[QuayOrgDesiredState],
        dry_run: bool,
    ) -> QuayRobotAccountsTaskResponse:
        """Send desired state to qontract-api and return task response."""
        request = QuayRobotAccountsReconcileRequest(
            organizations=organizations,
            dry_run=dry_run,
        )
        with self.log_api_exceptions():
            response = await reconcile_quay_robot_accounts(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gqlapi = gql.get_api()
        robots = self.get_robot_accounts(query_func=gqlapi.query)
        organizations = self.compile_desired_state(
            robots,
            org_name_filter=self.params.org_name,
        )

        if not organizations:
            logging.warning("No desired state found, nothing to reconcile")
            return

        task = await self.reconcile(organizations=organizations, dry_run=dry_run)

        if not dry_run:
            return

        task_result = await self.poll_task_status(
            status_url=task.status_url, result_type=QuayRobotAccountsTaskResult
        )
        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                "quay-robot-accounts-api: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            match action:
                case QuayRobotActionCreate():
                    logging.info(
                        f"create robot {action.robot_name} in {action.org_name}"
                    )
                case QuayRobotActionDelete():
                    logging.info(
                        f"delete robot {action.robot_name} from {action.org_name}"
                    )
                case QuayRobotActionAddTeam():
                    logging.info(f"add robot {action.robot_name} to team {action.team}")
                case QuayRobotActionRemoveTeam():
                    logging.info(
                        f"remove robot {action.robot_name} from team {action.team}"
                    )
                case QuayRobotActionSetRepoPermission():
                    logging.info(
                        f"set {action.permission} on {action.repo} for {action.robot_name}"
                    )
                case QuayRobotActionRemoveRepoPermission():
                    logging.info(
                        f"remove permission on {action.repo} for {action.robot_name}"
                    )

        if task_result.errors:
            errors_summary = "; ".join(task_result.errors)
            raise IntegrationError(
                f"quay-robot-accounts-api: {len(task_result.errors)} error(s): {errors_summary}"
            )
