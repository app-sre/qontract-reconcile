"""Endpoints-discovery reconciliation service.

Layer 3 (business logic) following ADR-014. Receives ready-to-use Layer 2
clients: no secret reads, client construction or direct API calls happen here.

Plan-and-apply: every endpoint change is calculated first, then a single merge
request is opened. `dry_run` is checked only at the apply step.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qontract_utils.differ import diff_any_iterables
from qontract_utils.vcs.provider_protocol import (
    CreateMergeRequestInput,
    FileAction,
    MergeRequestFile,
    MergeRequestInfo,
)

from qontract_api.integrations.endpoints_discovery.domain import (
    AppEndpointPlan,
    DesiredApp,
    DiscoveredRoute,
    NamespaceDesiredState,
    RouteLike,
)
from qontract_api.integrations.endpoints_discovery.metrics import (
    INTEGRATION_NAME,
    endpoints_discovery_apps_with_changes,
)
from qontract_api.integrations.endpoints_discovery.mr import (
    INTEGRATION,
    LABEL,
    VERSION,
    app_hash,
    compile_endpoint_name,
    endpoint_prefix,
    hash_apps,
    parse_endpoint_name,
    parse_merge_request_description,
    render_description,
    render_merge_request_content,
    render_template,
    render_title,
)
from qontract_api.integrations.endpoints_discovery.schemas import (
    AddEndpointAction,
    ChangeEndpointAction,
    DeleteEndpointAction,
    EndpointAction,
    EndpointsDiscoveryReconcileRequest,
    EndpointsDiscoveryTaskResult,
    MergeRequestStatus,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api.integrations.endpoints_discovery.mr import MergeRequestMetadata
    from qontract_api.kubernetes.workspace_client import KubernetesWorkspaceClient
    from qontract_api.vcs.vcs_workspace_client import VCSWorkspaceClient

logger = get_logger(__name__)

# Either name disables a cluster, so a cluster excluded from the legacy
# integration is not silently processed by the new one.
_DISABLED_INTEGRATION_NAMES = frozenset({INTEGRATION, f"{INTEGRATION}-api"})

_INVALID_MR_COMMENT = "Closing this MR because it is invalid or has conflicts."
_OUTDATED_MR_COMMENT = "Closing this MR because it's outdated."


@dataclass
class _AppPlan:
    """Calculated endpoint changes for one application."""

    app: DesiredApp
    endpoints_to_add: list[AppEndpointPlan] = field(default_factory=list)
    endpoints_to_change: list[AppEndpointPlan] = field(default_factory=list)
    endpoints_to_delete: list[AppEndpointPlan] = field(default_factory=list)
    actions: list[EndpointAction] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.endpoints_to_add
            or self.endpoints_to_change
            or self.endpoints_to_delete
        )


class EndpointsDiscoveryService:
    """Reconciles application endpoints against live OpenShift routes."""

    def __init__(
        self,
        cluster_clients: dict[str, KubernetesWorkspaceClient],
        vcs_client: VCSWorkspaceClient,
    ) -> None:
        self._cluster_clients = cluster_clients
        self._vcs_client = vcs_client

    def reconcile(
        self,
        request: EndpointsDiscoveryReconcileRequest,
        *,
        dry_run: bool = True,
    ) -> EndpointsDiscoveryTaskResult:
        """Plan endpoint changes and open at most one merge request."""
        errors: list[str] = []
        plans: list[_AppPlan] = []

        for app in request.apps:
            try:
                plan, plan_errors = self._plan_app(app, request.endpoint_template)
            except Exception as e:
                error_msg = f"{app.name}: unexpected error during planning: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)
                continue
            errors.extend(plan_errors)
            if plan.has_changes:
                plans.append(plan)
                self._log_plan(plan)

        actions = [action for plan in plans for action in plan.actions]
        apps_with_changes = len(plans)

        applied_actions: list[EndpointAction] = []
        mr_status: MergeRequestStatus | None = None
        mr_url: str | None = None

        if dry_run:
            logger.info(
                "Calculated endpoint changes",
                apps_with_changes=apps_with_changes,
                actions=len(actions),
            )
        elif not plans and errors:
            # Planning was incomplete, so an empty plan is not proof that an
            # open merge request is obsolete. Leave merge request state alone.
            mr_status = MergeRequestStatus.FAILED
        else:
            try:
                mr_status, mr_url, applied_actions, mr_errors = (
                    self._reconcile_merge_request(request, plans)
                )
                errors.extend(mr_errors)
            except Exception as e:
                error_msg = f"merge request reconciliation failed: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)
                mr_status = MergeRequestStatus.FAILED

        endpoints_discovery_apps_with_changes.labels(INTEGRATION_NAME).set(
            apps_with_changes
        )

        return EndpointsDiscoveryTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            apps_with_changes=apps_with_changes,
            mr_status=mr_status,
            mr_url=mr_url,
            errors=errors,
        )

    # --- Planning ---

    def _plan_app(
        self, app: DesiredApp, endpoint_template: str
    ) -> tuple[_AppPlan, list[str]]:
        plan = _AppPlan(app=app)
        errors: list[str] = []

        for namespace in app.namespaces:
            if not self._is_enabled(namespace):
                logger.debug(
                    "Integration disabled for cluster, skipping namespace",
                    cluster=namespace.cluster.cluster_name,
                    namespace=namespace.name,
                )
                continue
            if namespace.delete or not namespace.discover:
                # Deleted namespaces are handled by the removed-namespace
                # cleanup; filtered namespaces keep their endpoints untouched.
                continue

            add, change, delete, namespace_actions, namespace_errors = (
                self._plan_namespace(app, namespace, endpoint_template)
            )
            errors.extend(namespace_errors)
            plan.endpoints_to_add.extend(add)
            plan.endpoints_to_change.extend(change)
            plan.endpoints_to_delete.extend(delete)
            plan.actions.extend(namespace_actions)

        delete_plans, delete_actions = self._removed_namespace_cleanup(app)
        plan.endpoints_to_delete.extend(delete_plans)
        plan.actions.extend(delete_actions)

        return plan, errors

    def _plan_namespace(
        self,
        app: DesiredApp,
        namespace: NamespaceDesiredState,
        endpoint_template: str,
    ) -> tuple[
        list[AppEndpointPlan],
        list[AppEndpointPlan],
        list[AppEndpointPlan],
        list[EndpointAction],
        list[str],
    ]:
        cluster_name = namespace.cluster.cluster_name
        label = f"{cluster_name}/{namespace.name}"

        cluster_client = self._cluster_clients.get(cluster_name)
        if cluster_client is None:
            return [], [], [], [], [f"{label}: no client for cluster {cluster_name!r}"]

        try:
            namespace_exists = cluster_client.namespace_exists_uncached(namespace.name)
        except Exception as e:  # ruff: ignore[blind-except]
            return [], [], [], [], [f"{label}: failed to check namespace: {e}"]

        routes: Iterable[RouteLike] = ()
        if namespace_exists:
            try:
                routes = cluster_client.list_routes(namespace.name)
            except Exception as e:  # ruff: ignore[blind-except]
                # Fail closed: an unreadable namespace must not look empty.
                return [], [], [], [], [f"{label}: failed to list routes: {e}"]

        # A definitively absent namespace yields no routes, so its managed
        # endpoints are deleted, matching the legacy behaviour. API errors
        # never reach this point.
        discovered = self._filter_ignored_routes(
            self._group_routes(routes),
            {**app.labels, **namespace.labels},
        )

        prefix = endpoint_prefix(cluster_name, namespace.name)
        current = [
            endpoint for endpoint in app.end_points if endpoint.name.startswith(prefix)
        ]
        if not discovered and not current:
            return [], [], [], [], []

        diff = diff_any_iterables(
            current=current,
            desired=discovered,
            current_key=lambda endpoint: endpoint.name,
            desired_key=lambda route: compile_endpoint_name(prefix, route.name),
            # Only the URL is compared; the template owns everything else.
            equal=lambda endpoint, route: endpoint.url == route.url,
        )

        add = [
            AppEndpointPlan(
                name=compile_endpoint_name(prefix, route.name),
                data=render_template(
                    endpoint_template,
                    endpoint_name=compile_endpoint_name(prefix, route.name),
                    route=route,
                ),
            )
            for route in diff.add.values()
        ]
        change = [
            AppEndpointPlan(
                name=pair.current.name,
                data=render_template(
                    endpoint_template,
                    endpoint_name=compile_endpoint_name(prefix, pair.desired.name),
                    route=pair.desired,
                ),
            )
            for pair in diff.change.values()
        ]
        delete = [
            AppEndpointPlan(name=endpoint.name) for endpoint in diff.delete.values()
        ]

        actions: list[EndpointAction] = [
            AddEndpointAction(
                app_name=app.name,
                app_path=app.path,
                cluster=cluster_name,
                namespace=namespace.name,
                endpoint_name=endpoint.name,
                data=endpoint.data,
            )
            for endpoint in add
        ]
        actions.extend(
            ChangeEndpointAction(
                app_name=app.name,
                app_path=app.path,
                cluster=cluster_name,
                namespace=namespace.name,
                endpoint_name=endpoint.name,
                data=endpoint.data,
            )
            for endpoint in change
        )
        actions.extend(
            DeleteEndpointAction(
                app_name=app.name,
                app_path=app.path,
                endpoint_name=endpoint.name,
                cluster=cluster_name,
                namespace=namespace.name,
            )
            for endpoint in delete
        )

        return add, change, delete, actions, []

    @staticmethod
    def _removed_namespace_cleanup(
        app: DesiredApp,
    ) -> tuple[list[AppEndpointPlan], list[EndpointAction]]:
        """Delete endpoints whose cluster/namespace is no longer configured."""
        configured = {
            (namespace.cluster.cluster_name, namespace.name)
            for namespace in app.namespaces
            if not namespace.delete
        }

        plans: list[AppEndpointPlan] = []
        actions: list[EndpointAction] = []
        for endpoint in app.end_points:
            try:
                cluster_name, namespace_name, _ = parse_endpoint_name(endpoint.name)
            except ValueError:
                # Manual endpoint, not managed by this integration.
                continue
            if (cluster_name, namespace_name) in configured:
                continue
            plans.append(AppEndpointPlan(name=endpoint.name))
            actions.append(
                DeleteEndpointAction(
                    app_name=app.name,
                    app_path=app.path,
                    endpoint_name=endpoint.name,
                    cluster=cluster_name,
                    namespace=namespace_name,
                )
            )

        return plans, actions

    @staticmethod
    def _is_enabled(namespace: NamespaceDesiredState) -> bool:
        return not _DISABLED_INTEGRATION_NAMES.intersection(
            namespace.cluster.disabled_integrations
        )

    @staticmethod
    def _group_routes(routes: Iterable[RouteLike]) -> list[DiscoveredRoute]:
        """Merge routes sharing a host and TLS flag into one discovered route."""
        grouped: defaultdict[tuple[str, bool], list[str]] = defaultdict(list)
        for route in routes:
            grouped[route.host, route.tls].append(route.name)

        return [
            DiscoveredRoute(
                name="|".join(sorted(names)),
                host=host,
                tls=tls,
            )
            for (host, tls), names in grouped.items()
        ]

    @staticmethod
    def _filter_ignored_routes(
        routes: list[DiscoveredRoute], labels: dict[str, str]
    ) -> list[DiscoveredRoute]:
        return [
            route for route in routes if f"{INTEGRATION}-{route.name}" not in labels
        ]

    @staticmethod
    def _log_plan(plan: _AppPlan) -> None:
        for action in plan.actions:
            logger.info(
                f"{plan.app.name}: {action.action_type}",
                endpoint=action.endpoint_name,
            )

    # --- Applying ---

    def _reconcile_merge_request(
        self,
        request: EndpointsDiscoveryReconcileRequest,
        plans: list[_AppPlan],
    ) -> tuple[MergeRequestStatus, str | None, list[EndpointAction], list[str]]:
        desired_hash = self._plans_hash(plans)
        valid = self._close_invalid_merge_requests()

        if valid:
            mr, metadata = valid[0]
            if metadata.hash == desired_hash:
                logger.info("Open merge request is up to date", mr_url=mr.web_url)
                return MergeRequestStatus.EXISTS, mr.web_url, [], []
            logger.info("Open merge request is outdated, closing it", mr_url=mr.web_url)
            self._vcs_client.close_merge_request(
                mr.web_url, comment=_OUTDATED_MR_COMMENT
            )
            # A replacement only opens on the next run, so a disabled deletion
            # cannot leave two open merge requests behind.
            return MergeRequestStatus.CLOSED_OUTDATED, None, [], []

        target_branch = request.app_interface.target_branch
        file_operations: list[MergeRequestFile] = []
        applied_actions: list[EndpointAction] = []
        for plan in plans:
            repo_path = _repo_path(plan.app.path)
            current_content = self._vcs_client.get_file(repo_path, ref=target_branch)
            if current_content is None:
                error_msg = (
                    f"{plan.app.name}: file {plan.app.path} is missing or unreadable "
                    f"on {target_branch}; no merge request opened"
                )
                logger.error(error_msg)
                return MergeRequestStatus.FAILED, None, [], [error_msg]

            merged_content = render_merge_request_content(
                current_content=current_content,
                endpoints_to_add=[item.data for item in plan.endpoints_to_add],
                endpoints_to_change={
                    item.name: item.data for item in plan.endpoints_to_change
                },
                endpoints_to_delete=[item.name for item in plan.endpoints_to_delete],
            )
            if merged_content == current_content:
                # The branch already matches the plan, so this app would have
                # produced an empty commit.
                continue

            file_operations.append(
                MergeRequestFile(
                    path=repo_path,
                    action=FileAction.UPDATE,
                    content=merged_content,
                    commit_message=(
                        f"endpoints-discovery: update application endpoints for "
                        f"{plan.app.name}"
                    ),
                )
            )
            applied_actions.extend(plan.actions)

        if not file_operations:
            return MergeRequestStatus.NOT_NEEDED, None, [], []

        mr_url = self._vcs_client.create_merge_request(
            CreateMergeRequestInput(
                title=render_title(),
                description=render_description(plan_hash=desired_hash),
                target_branch=target_branch,
                file_operations=file_operations,
                labels=[LABEL],
                auto_merge=request.auto_merge,
            )
        )
        logger.info(
            "Opened merge request",
            mr_url=mr_url,
            file_operations=len(file_operations),
        )
        return MergeRequestStatus.CREATED, mr_url, applied_actions, []

    def _close_invalid_merge_requests(
        self,
    ) -> list[tuple[MergeRequestInfo, MergeRequestMetadata]]:
        """Close MRs that are conflicted, malformed, or from another version."""
        valid: list[tuple[MergeRequestInfo, MergeRequestMetadata]] = []
        for mr in self._vcs_client.list_open_merge_requests(label=LABEL):
            metadata = parse_merge_request_description(mr.description)
            if (
                mr.has_conflicts
                or metadata is None
                or metadata.integration != INTEGRATION
                or metadata.version != VERSION
            ):
                logger.info("Closing invalid merge request", mr_url=mr.web_url)
                self._vcs_client.close_merge_request(
                    mr.web_url, comment=_INVALID_MR_COMMENT
                )
                continue
            valid.append((mr, metadata))
        return valid

    @staticmethod
    def _plans_hash(plans: list[_AppPlan]) -> str:
        return hash_apps([
            (
                plan.app.name,
                app_hash(
                    plan.app.path,
                    plan.endpoints_to_add,
                    plan.endpoints_to_change,
                    plan.endpoints_to_delete,
                ),
            )
            for plan in plans
        ])


def _repo_path(app_path: str) -> str:
    """Map an App-Interface path to its repository path."""
    return f"data/{app_path.lstrip('/')}"
