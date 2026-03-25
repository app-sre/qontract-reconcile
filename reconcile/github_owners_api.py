"""GitHub organization owner reconciliation via qontract-api.

This is the client-side integration that calls qontract-api instead of
directly managing GitHub organization owners.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).

Key differences from reconcile/github_owners.py:
- Suffix '_api' indicates API-based integration
- GraphQL queries for desired state happen client-side here
- Actual reconciliation (GitHub API calls) happens server-side (qontract-api)
- Uses qenerate-generated types instead of raw dict access

Design note — add-only behavior:
    Owner removal is intentionally NOT supported. The original github-owners
    integration only adds owners and never removes them. This migration
    preserves that behavior as a deliberate safety decision: removing org
    admins is a high-impact operation requiring explicit manual review.
"""

import logging
from collections import defaultdict
from collections.abc import Callable

from qontract_api_client.api.integrations.github_owners import (
    GithubOwnersTaskResponse,
)
from qontract_api_client.api.integrations.github_owners import (
    asyncio as reconcile_github_owners,
)
from qontract_api_client.api.integrations.github_owners_task_status import (
    asyncio as github_owners_task_status,
)
from qontract_api_client.models.github_org_desired_state import (
    GithubOrgDesiredState,
)
from qontract_api_client.models.github_owners_reconcile_request import (
    GithubOwnersReconcileRequest,
)
from qontract_api_client.models.secret import Secret
from qontract_api_client.models.task_status import TaskStatus
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.common.github_orgs import GithubOrgV1
from reconcile.gql_definitions.common.github_orgs import query as github_orgs_query
from reconcile.gql_definitions.github_owners_api.roles import (
    PermissionGithubOrgTeamV1,
    PermissionGithubOrgV1,
    RoleV1,
)
from reconcile.gql_definitions.github_owners_api.roles import query as roles_query
from reconcile.utils import expiration, gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

QONTRACT_INTEGRATION = "github-owners-api"


class GithubOwnersIntegrationParams(PydanticRunParams):
    """Parameters for github-owners-api integration."""

    org_name: str | None = None


class GithubOwnersIntegration(
    QontractReconcileApiIntegration[GithubOwnersIntegrationParams]
):
    """Manage GitHub organization owner membership via qontract-api.

    This integration:
    1. Queries App-Interface for roles with github-org/github-org-team owner permissions
    2. Filters expired roles
    3. Queries App-Interface for GitHub org configs (to get API tokens)
    4. Compiles the desired owner state per org
    5. Sends the complete desired state to qontract-api for reconciliation

    Owner removal is intentionally not supported. See module docstring for rationale.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_roles(query_func: Callable) -> list[RoleV1]:
        """Return all roles from app-interface, filtered for expiration."""
        result = roles_query(query_func=query_func)
        return expiration.filter(result.roles or [])

    @staticmethod
    def get_github_orgs(query_func: Callable) -> dict[str, GithubOrgV1]:
        """Return all GitHub org configs keyed by org name."""
        result = github_orgs_query(query_func=query_func)
        return {org.name: org for org in result.orgs or []}

    def compile_desired_state(
        self,
        roles: list[RoleV1],
        github_orgs: dict[str, GithubOrgV1],
        org_name_filter: str | None = None,
    ) -> list[GithubOrgDesiredState]:
        """Compile the desired owner state from roles and org configs.

        Groups all github-org and github-org-team owner permissions by org,
        collects all users and bots with those permissions, and matches them
        to the org's GitHub API token.

        Args:
            roles: All app-interface roles (already filtered for expiration)
            github_orgs: GitHub org configs keyed by org name
            org_name_filter: If set, only include this org in the result

        Returns:
            List of GithubOrgDesiredState ready to send to qontract-api
        """
        # Collect desired owners per org from roles
        owners_by_org: dict[str, set[str]] = defaultdict(set)

        for role in roles:
            for permission in role.permissions or []:
                if not isinstance(
                    permission, (PermissionGithubOrgV1, PermissionGithubOrgTeamV1)
                ):
                    continue
                if permission.role != "owner":
                    continue

                org = permission.org
                if org_name_filter and org != org_name_filter:
                    continue

                for user in role.users:
                    if user.github_username:
                        owners_by_org[org].add(user.github_username.lower())
                for bot in role.bots:
                    if bot.github_username:
                        owners_by_org[org].add(bot.github_username.lower())

        # Build desired state list, joining with org token configs
        desired: list[GithubOrgDesiredState] = []
        for org, owners in owners_by_org.items():
            org_config = github_orgs.get(org)
            if not org_config:
                logging.warning(
                    f"No GitHub org config found for '{org}' — skipping. "
                    "Ensure the org is defined in app-interface."
                )
                continue

            vault_secret = org_config.token
            desired.append(
                GithubOrgDesiredState(
                    org_name=org,
                    owners=sorted(owners),
                    token=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=vault_secret.path,
                        field=vault_secret.field,
                        version=vault_secret.version,
                    ),
                )
            )

        return desired

    async def reconcile(
        self,
        organizations: list[GithubOrgDesiredState],
        dry_run: bool,
    ) -> GithubOwnersTaskResponse:
        """Send desired state to qontract-api and return task response."""
        request = GithubOwnersReconcileRequest(
            organizations=organizations,
            dry_run=dry_run,
        )
        response = await reconcile_github_owners(
            client=self.qontract_api_client, body=request
        )
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gqlapi = gql.get_api()
        roles = self.get_roles(query_func=gqlapi.query)
        github_orgs = self.get_github_orgs(query_func=gqlapi.query)

        organizations = self.compile_desired_state(
            roles,
            github_orgs,
            org_name_filter=self.params.org_name,
        )

        if not organizations:
            logging.warning("No desired state found, nothing to reconcile")
            return

        task = await self.reconcile(organizations=organizations, dry_run=dry_run)

        if not dry_run:
            # In non-dry-run, the task completes asynchronously in the background
            # and change events will be published via the events framework.
            return

        # Wait for task completion and log actions
        task_result = await github_owners_task_status(
            client=self.qontract_api_client, task_id=task.id, timeout=300
        )

        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                "github-owners-api: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            logging.info(f"{action.action_type=} {action.org_name=} {action.username=}")

        if task_result.errors:
            errors_summary = "; ".join(task_result.errors)
            raise IntegrationError(
                f"github-owners-api: {len(task_result.errors)} error(s): {errors_summary}"
            )
