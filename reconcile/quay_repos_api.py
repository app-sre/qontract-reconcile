"""Quay repos reconciliation via qontract-api.

Client-side sibling of reconcile/quay_repos.py (see ADR-008).

Differences from reconcile/quay_repos.py:
- Suffix '_api' indicates API-based integration
- Desired state (repos) is fetched client-side via GraphQL
- Business logic (diff + reconcile) runs server-side in qontract-api
- No direct Quay API calls; secrets are passed as references, not values

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

from qontract_api_client.client import quay_repos as quay_repos_reconcile
from qontract_api_client.schemas import (
    QuayOrgConfig,
    QuayOrgKey,
    QuayRepoConfig,
    QuayReposReconcileRequest,
    QuayReposTaskResponse,
    QuayReposTaskResult,
    Secret,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.quay_repos_api.apps_quay_repos import (
    AppQuayReposItemsV1,
    AppV1,
)
from reconcile.gql_definitions.quay_repos_api.apps_quay_repos import (
    query as apps_query,
)
from reconcile.gql_definitions.quay_repos_api.quay_orgs import QuayOrgV1
from reconcile.gql_definitions.quay_repos_api.quay_orgs import query as quay_orgs_query
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

QONTRACT_INTEGRATION = "quay-repos-api"


class OrgKey(NamedTuple):
    instance: str
    org_name: str


QONTRACT_INTEGRATION_UPSTREAM = "quay-repos"


class QuayReposIntegrationParams(PydanticRunParams):
    pass


class QuayReposIntegration(QontractReconcileApiIntegration[QuayReposIntegrationParams]):
    """Manage Quay repositories via qontract-api.

    1. Queries App-Interface for Quay org configurations
    2. Queries App-Interface for desired repo state (from apps)
    3. Compiles per-org desired state with Secret references (no token values)
    4. Sends to qontract-api for reconciliation
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_quay_orgs(query_func: Callable[..., dict[Any, Any]]) -> list[QuayOrgV1]:
        data = quay_orgs_query(query_func=query_func)
        return list(data.quay_orgs or [])

    @staticmethod
    def get_apps(query_func: Callable[..., dict[Any, Any]]) -> list[AppV1]:
        data = apps_query(query_func=query_func)
        return list(data.apps or [])

    @staticmethod
    def _build_repos_map(apps: list[AppV1]) -> dict[OrgKey, list[AppQuayReposItemsV1]]:
        """Build a map of OrgKey -> list of repo items from apps."""
        repos_map: dict[OrgKey, list[AppQuayReposItemsV1]] = {}
        for app in apps:
            for quay_repo in app.quay_repos or []:
                key = OrgKey(
                    instance=quay_repo.org.instance.name, org_name=quay_repo.org.name
                )
                repos_map.setdefault(key, []).extend(quay_repo.items)
        return repos_map

    def compile_desired_state(
        self,
        orgs: list[QuayOrgV1],
        apps: list[AppV1],
    ) -> list[QuayOrgConfig]:
        """Compile per-org desired state from GraphQL data.

        Only includes orgs that have managedRepos or mirror set and have
        an automation token. Repos are sourced from app definitions in
        app-interface. Secret references are passed (no token values).
        """
        repos_map = self._build_repos_map(apps)
        result: list[QuayOrgConfig] = []

        for org in orgs:
            if not org.managed_repos and not org.mirror:
                continue
            if not org.automation_token:
                logging.warning(
                    f"No automationToken for {org.instance.name}/{org.name} — skipping"
                )
                continue

            key = OrgKey(instance=org.instance.name, org_name=org.name)
            repo_items = repos_map.get(key, [])

            counts = Counter(item.name for item in repo_items)
            duplicates = {name for name, count in counts.items() if count > 1}
            if duplicates:
                raise IntegrationError(
                    f"{org.instance.name}/{org.name}: duplicate repo name(s) defined "
                    f"across multiple apps: {', '.join(sorted(duplicates))}"
                )

            mirror: QuayOrgKey | None = None
            if org.mirror:
                mirror = QuayOrgKey(
                    instance=org.mirror.instance.name,
                    org_name=org.mirror.name,
                )

            result.append(
                QuayOrgConfig(
                    instance=org.instance.name,
                    org_name=org.name,
                    base_url=org.instance.url,
                    automation_token=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=org.automation_token.path,
                        field=org.automation_token.field,
                        version=org.automation_token.version,
                    ),
                    managed_repos=org.managed_repos,
                    mirror=mirror,
                    repos=[
                        QuayRepoConfig(
                            name=item.name,
                            public=item.public,
                            description=(item.description or "").strip(),
                        )
                        for item in repo_items
                    ],
                )
            )

        return result

    async def reconcile(
        self,
        orgs: list[QuayOrgConfig],
        dry_run: bool,
    ) -> QuayReposTaskResponse:
        """Send desired state to qontract-api."""
        request = QuayReposReconcileRequest(orgs=orgs, dry_run=dry_run)
        with self.log_api_exceptions():
            response = await quay_repos_reconcile(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gqlapi = gql.get_api()
        orgs = self.get_quay_orgs(query_func=gqlapi.query)
        apps = self.get_apps(query_func=gqlapi.query)

        desired_orgs = self.compile_desired_state(orgs=orgs, apps=apps)

        if not desired_orgs:
            logging.warning("No desired state found, nothing to reconcile")
            return

        task = await self.reconcile(orgs=desired_orgs, dry_run=dry_run)

        if not dry_run:
            # In non-dry-run, the task runs asynchronously in the background.
            # The reconcile loop re-queues on the next schedule tick; deduplication
            # prevents overlapping tasks (see tasks.py deduplicated_task).
            return

        task_result = await self.poll_task_status(
            status_url=task.status_url,
            result_type=QuayReposTaskResult,
        )
        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            logging.info(
                f"{action.action_type=} {action.instance=} {action.org_name=} {action.repo_name=}"
            )

        if task_result.errors:
            errors_summary = "; ".join(task_result.errors)
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: {len(task_result.errors)} error(s): {errors_summary}"
            )
