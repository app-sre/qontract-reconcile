"""GitLab projects reconciliation via qontract-api.

Client-side sibling of reconcile/gitlab_projects.py (see ADR-008).

Differences from reconcile/gitlab_projects.py:
- Suffix '_api' indicates API-based integration
- Desired state (instances/groups/projects) is fetched client-side via
  GraphQL, including validating every requested project against
  app-interface codeComponents (ADR-002) - the server never needs to know
  about codeComponents or apps
- Business logic (diff + reconcile) runs server-side in qontract-api
- No direct GitLab API calls; secrets are passed as references, not values

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qontract_api_client.client import gitlab_projects as gitlab_projects_reconcile
from qontract_api_client.schemas import (
    GitlabGroupConfig,
    GitlabInstanceConfig,
    GitlabProjectConfig,
    GitlabProjectsReconcileRequest,
    GitlabProjectsTaskResponse,
    GitlabProjectsTaskResult,
    Secret,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.gitlab_projects.app_code_components import (
    AppCodeComponentsV1,
)
from reconcile.gql_definitions.gitlab_projects.app_code_components import (
    query as code_components_query,
)
from reconcile.gql_definitions.gitlab_projects.gitlab_instances import (
    GitlabInstanceV1,
)
from reconcile.gql_definitions.gitlab_projects.gitlab_instances import (
    query as instances_query,
)
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from collections.abc import Callable

QONTRACT_INTEGRATION = "gitlab-projects-api"


class GitlabProjectsIntegrationParams(PydanticRunParams):
    """Parameters for gitlab-projects-api integration."""

    instance_name: str | None = None
    project_names: frozenset[str] | None = None


class GitLabProjectsIntegration(
    QontractReconcileApiIntegration[GitlabProjectsIntegrationParams]
):
    """Create GitLab projects via qontract-api.

    This integration:
    1. Queries App-Interface for GitLab instances and their requested projects/groups
    2. Queries App-Interface for app codeComponents, to validate each requested project
    3. Filters out projects with no matching codeComponent, failing the run if any are found
    4. Sends the complete desired state to qontract-api for reconciliation
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_gitlab_instances(
        query_func: Callable[..., dict[Any, Any]],
    ) -> list[GitlabInstanceV1]:
        data = instances_query(query_func=query_func)
        if not data.instances:
            raise IntegrationError("no GitLab instances found")
        return data.instances

    @staticmethod
    def get_code_components(
        query_func: Callable[..., dict[Any, Any]],
    ) -> list[AppCodeComponentsV1]:
        data = code_components_query(query_func=query_func)
        return [
            code_component
            for app in data.apps or []
            for code_component in app.code_components or []
        ]

    @staticmethod
    def filter_requested_projects(
        gl_instances: list[GitlabInstanceV1],
        allowed_instance_name: str | None,
        allowed_project_names: frozenset[str] | None,
    ) -> list[GitlabInstanceV1]:
        """Return instances/projects narrowed to the given filters, for targeted debug runs."""
        instances = [
            instance
            for instance in gl_instances
            if not allowed_instance_name or instance.name == allowed_instance_name
        ]
        if not allowed_project_names:
            return instances

        filtered_instances = []
        for instance in instances:
            project_requests = [
                project_request.model_copy(
                    update={
                        "projects": [
                            p
                            for p in project_request.projects
                            if p in allowed_project_names
                        ]
                    }
                )
                for project_request in instance.project_requests or []
            ]
            filtered_instances.append(
                instance.model_copy(
                    update={
                        "project_requests": [
                            pr for pr in project_requests if pr.projects
                        ]
                    }
                )
            )
        return filtered_instances

    def compile_desired_state(
        self,
        gl_instances: list[GitlabInstanceV1],
        code_components: list[AppCodeComponentsV1],
    ) -> list[GitlabInstanceConfig]:
        """Filter each requested project to those declared via an app-interface
        codeComponent.

        A project whose codeComponent has `resource: bundle` is flagged so it
        can be initialized as a SaaS bundle repo (README + staging/production
        branches) instead of a plain empty repo.

        Raises:
            IntegrationError: If any requested project has no matching
                codeComponent.
        """
        declared_urls = {c.url for c in code_components}
        bundle_urls = {c.url for c in code_components if c.resource == "bundle"}

        instances: list[GitlabInstanceConfig] = []
        missing_urls: list[str] = []
        for instance in gl_instances:
            group_requests: list[GitlabGroupConfig] = []
            for project_request in instance.project_requests or []:
                valid_projects: list[GitlabProjectConfig] = []
                for project_name in project_request.projects:
                    project_url = (
                        f"{instance.url}/{project_request.group}/{project_name}"
                    )
                    if project_url not in declared_urls:
                        logging.error(f"{project_url} missing from all codeComponents")
                        missing_urls.append(project_url)
                        continue
                    valid_projects.append(
                        GitlabProjectConfig(
                            name=project_name,
                            is_saas_bundle=project_url in bundle_urls,
                        )
                    )
                if valid_projects:
                    group_requests.append(
                        GitlabGroupConfig(
                            group=project_request.group, projects=valid_projects
                        )
                    )
            if not group_requests:
                continue
            instances.append(
                GitlabInstanceConfig(
                    name=instance.name,
                    url=instance.url,
                    ssl_verify=(
                        instance.ssl_verify if instance.ssl_verify is not None else True
                    ),
                    token=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=instance.token.path,
                        field=instance.token.field,
                        version=instance.token.version,
                    ),
                    groups=group_requests,
                )
            )

        if missing_urls:
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: {len(missing_urls)} project(s) missing "
                f"from codeComponents: {', '.join(sorted(missing_urls))}"
            )

        return instances

    async def reconcile(
        self,
        instances: list[GitlabInstanceConfig],
        dry_run: bool,
    ) -> GitlabProjectsTaskResponse:
        """Send desired state to qontract-api."""
        request = GitlabProjectsReconcileRequest(instances=instances, dry_run=dry_run)
        with self.log_api_exceptions():
            response = await gitlab_projects_reconcile(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gqlapi: gql.GqlApi = gql.get_api()
        gl_instances = self.get_gitlab_instances(query_func=gqlapi.query)
        gl_instances = self.filter_requested_projects(
            gl_instances, self.params.instance_name, self.params.project_names
        )
        code_components = self.get_code_components(query_func=gqlapi.query)
        desired_state = self.compile_desired_state(gl_instances, code_components)

        if not desired_state:
            logging.warning("No desired state found, nothing to reconcile")
            return

        task = await self.reconcile(instances=desired_state, dry_run=dry_run)

        if not dry_run:
            return

        task_result = await self.poll_task_status(
            status_url=task.status_url,
            result_type=GitlabProjectsTaskResult,
        )
        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            logging.info(
                f"{action.action_type=} {action.instance=} {action.group=} {action.project_name=}"
            )

        if task_result.errors:
            errors_summary = "; ".join(task_result.errors)
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: {len(task_result.errors)} error(s): {errors_summary}"
            )
