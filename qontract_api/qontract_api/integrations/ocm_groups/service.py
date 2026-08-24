"""OCM groups reconciliation service.

Manages OCM cluster group memberships (dedicated-admins, cluster-admins).
Refactored from reconcile/ocm_groups.py for the API context (ADR-007).
"""

from __future__ import annotations

import operator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import httpx2
import pydantic
from qontract_utils.differ import diff_iterables

from qontract_api.integrations.ocm_groups.metrics import (
    INTEGRATION_NAME,
    ocm_groups_managed_clusters,
    ocm_groups_reconcile_errors,
    ocm_groups_reconciled,
)
from qontract_api.integrations.ocm_groups.schemas import (
    OcmGroupsAction,
    OcmGroupsActionAddUser,
    OcmGroupsActionDeleteUser,
    OcmGroupsTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.ocm.ocm_client_factory import create_ocm_workspace_client

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.integrations.ocm_groups.domain import (
        OcmGroupsCluster,
        OcmGroupUser,
    )
    from qontract_api.ocm.domain import OcmConnectionParams
    from qontract_api.ocm.ocm_workspace_client import OcmWorkspaceClient
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)

# OCM-manageable groups - matches reconcile/utils/ocm/base.py::OCMClusterGroupId
VALID_OCM_GROUPS = frozenset({"dedicated-admins", "cluster-admins"})

# HTTP status codes considered non-fatal during cluster-fetch operations.
# 404 = cluster or group not found in OCM (expected when not yet configured).
_NON_FATAL_STATUS_CODES = frozenset({404})


def _is_fatal_fetch_error(exc: Exception) -> bool:
    """Distinguish fatal from non-fatal cluster-fetch failures.

    Mirrors the _UnresolvedDesiredStateError.fatal pattern from the reference
    ocm_oidc_idp integration. Fatal errors (auth failures, timeouts,
    permission errors) must surface as task errors; non-fatal errors
    (e.g. group not yet configured, 404) are logged and the cluster is
    skipped for this reconcile without failing the overall run.

    Uses proper exception type checking instead of fragile substring
    matching on error messages — a 500 whose body happens to contain
    "not found" would otherwise be misclassified as non-fatal.
    """
    if isinstance(exc, httpx2.HTTPStatusError):
        return exc.response.status_code not in _NON_FATAL_STATUS_CODES
    return True


class _GroupMembershipState(pydantic.BaseModel):
    """Internal diffing unit: one user membership in a cluster group.

    Equality delegates to the (cluster, group, user) triple only - the
    ``cluster_id`` field is informational (needed for OCM API calls when
    applying actions) but must not drive add/delete decisions.
    """

    cluster: str
    group: str
    user: str
    cluster_id: str

    # Custom __eq__ delegates to the membership triple only, so instances are
    # intentionally unhashable.  mypy has no clean way to type this pattern
    # outside of @dataclass.
    __hash__ = None  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _GroupMembershipState):
            return NotImplemented
        return (self.cluster, self.group, self.user) == (
            other.cluster,
            other.group,
            other.user,
        )


class OcmGroupsService:
    """Service for reconciling OCM cluster group memberships.

    Fetches current state (existing group memberships per cluster from OCM),
    receives desired state (from client-side GraphQL), diffs them via
    ``diff_iterables``, and executes add/delete user actions against OCM.

    Uses dependency injection to keep the service decoupled from implementation
    details.
    """

    def __init__(
        self,
        cache: CacheBackend,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        self.cache = cache
        self.secret_manager = secret_manager
        self.settings = settings

    @staticmethod
    def _expose_cluster_metrics(
        ocm_environment: str, clusters: Iterable[OcmGroupsCluster]
    ) -> None:
        """Expose ocm_groups_managed_clusters gauge for each managed cluster."""
        for cluster in clusters:
            ocm_groups_managed_clusters.labels(
                INTEGRATION_NAME, ocm_environment, cluster.name
            ).set(1)

    @staticmethod
    def _fetch_current_state(
        workspace_client: OcmWorkspaceClient,
        clusters: list[OcmGroupsCluster],
        *,
        max_workers: int,
    ) -> tuple[list[_GroupMembershipState], set[str], list[str]]:
        """Fetch existing group memberships for every cluster, concurrently.

        Each cluster's OCM query is an independent HTTP round-trip - fetching
        them serially would make wall-clock time scale linearly with cluster
        count, for no benefit (OcmWorkspaceClient already shares one OcmApi
        connection across threads).  A single cluster's OCM query failing does
        not abort the whole run - it is logged and that cluster is skipped for
        this reconcile, matching the per-cluster error isolation used by the
        reference ocm_oidc_idp integration.

        Returns:
            A tuple of (current_state, unresolved_clusters, errors).
            ``unresolved_clusters`` contains cluster names whose current state
            could not be fetched - the caller must exclude any matching
            desired-state entry from the diff to avoid treating a read failure
            as "no users exist" (which would generate spurious delete actions).
            ``errors`` collects messages from fatal failures (auth errors,
            timeouts, permission errors). Non-fatal failures (e.g. 404 for
            clusters not yet configured) are logged and skipped without marking
            as errors - see ``_is_fatal_fetch_error()``.
        """
        current_state: list[_GroupMembershipState] = []
        unresolved_clusters: set[str] = set()
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_cluster = {
                executor.submit(
                    workspace_client.get_cluster_groups, cluster.cluster_id
                ): cluster
                for cluster in clusters
            }
            for future in as_completed(future_to_cluster):
                cluster = future_to_cluster[future]
                try:
                    groups = future.result()
                except Exception as e:
                    fatal = _is_fatal_fetch_error(e)
                    message = (
                        f"Failed to fetch groups for cluster "
                        f"{cluster.name}; skipping for this reconcile: {e}"
                    )
                    if fatal:
                        logger.exception(message)
                        errors.append(message)
                    else:
                        logger.warning(message)
                    unresolved_clusters.add(cluster.name)
                    continue
                for group in groups:
                    # Only process groups that are managed on this cluster
                    if group.id not in cluster.managed_groups:
                        continue
                    # Only process OCM-valid groups
                    if group.id not in VALID_OCM_GROUPS:
                        continue
                    current_state.extend(
                        _GroupMembershipState(
                            cluster=cluster.name,
                            group=group.id,
                            user=user,
                            cluster_id=cluster.cluster_id,
                        )
                        for user in group.users
                    )
        return current_state, unresolved_clusters, errors

    @staticmethod
    def _build_desired_state(
        clusters: list[OcmGroupsCluster],
        raw_desired: list[OcmGroupUser],
    ) -> list[_GroupMembershipState]:
        """Build the desired state as ``_GroupMembershipState`` instances.

        Filters desired memberships to only those whose (cluster, group) pair
        is both a valid OCM group and declared as managed on the respective
        cluster.  Desired memberships outside this scope are dropped - they
        would otherwise produce add actions for groups the current-state path
        never reads.
        """
        # Build cluster name -> cluster for lookups
        cluster_map = {c.name: c for c in clusters}
        # Build the set of (cluster, group) pairs that are both valid OCM
        # groups and declared as managed on the respective cluster.
        managed_pairs: set[tuple[str, str]] = set()
        for c in clusters:
            for g in c.managed_groups:
                if g in VALID_OCM_GROUPS:
                    managed_pairs.add((c.name, g))

        desired_state: list[_GroupMembershipState] = []
        for u in raw_desired:
            if (u.cluster, u.group) not in managed_pairs:
                continue
            cluster = cluster_map.get(u.cluster)
            if not cluster:
                continue
            desired_state.append(
                _GroupMembershipState(
                    cluster=u.cluster,
                    group=u.group,
                    user=u.user,
                    cluster_id=cluster.cluster_id,
                )
            )
        return desired_state

    @staticmethod
    def _diff_key(state: _GroupMembershipState) -> tuple[str, str, str]:
        """Identity key for diff_iterables: (cluster, group, user)."""
        return (state.cluster, state.group, state.user)

    @staticmethod
    def _process_deletes(
        workspace_client: OcmWorkspaceClient,
        delete_states: Iterable[_GroupMembershipState],
        *,
        dry_run: bool,
    ) -> tuple[list[OcmGroupsAction], list[OcmGroupsAction], list[str]]:
        """Process delete actions (users to remove from groups).

        Collects errors per-action without short-circuiting, so one failing
        delete does not prevent other deletes from being attempted.
        """
        actions: list[OcmGroupsAction] = []
        applied: list[OcmGroupsAction] = []
        errors: list[str] = []

        for state in delete_states:
            action = OcmGroupsActionDeleteUser(
                cluster=state.cluster, group=state.group, user=state.user
            )
            actions.append(action)
            if dry_run:
                continue
            try:
                workspace_client.delete_user_from_group(
                    state.cluster_id, state.group, state.user
                )
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{state.cluster}: failed to delete user={state.user} "
                    f"from group={state.group}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)

        return actions, applied, errors

    @staticmethod
    def _process_adds(
        workspace_client: OcmWorkspaceClient,
        add_states: Iterable[_GroupMembershipState],
        *,
        dry_run: bool,
    ) -> tuple[list[OcmGroupsAction], list[OcmGroupsAction], list[str]]:
        """Process add actions (users to add to groups).

        Collects errors per-action without short-circuiting, so one failing
        add does not prevent other adds from being attempted.
        """
        actions: list[OcmGroupsAction] = []
        applied: list[OcmGroupsAction] = []
        errors: list[str] = []

        for state in add_states:
            action = OcmGroupsActionAddUser(
                cluster=state.cluster, group=state.group, user=state.user
            )
            actions.append(action)
            if dry_run:
                continue
            try:
                workspace_client.add_user_to_group(
                    state.cluster_id, state.group, state.user
                )
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{state.cluster}: failed to add user={state.user} "
                    f"to group={state.group}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)

        return actions, applied, errors

    def reconcile(
        self,
        ocm_environment: str,
        ocm_connection: OcmConnectionParams,
        clusters: list[OcmGroupsCluster],
        desired_state: list[OcmGroupUser],
        *,
        dry_run: bool = True,
    ) -> OcmGroupsTaskResult:
        """Reconcile OCM cluster group memberships for one OCM environment."""
        self._expose_cluster_metrics(ocm_environment, clusters)
        desired = self._build_desired_state(clusters, desired_state)

        actions: list[OcmGroupsAction] = []
        applied_actions: list[OcmGroupsAction] = []
        errors: list[str] = []

        # A single OcmWorkspaceClient (and the OcmApi connection it lazily
        # builds) is reused for every cluster's current-state fetch and every
        # mutation below, instead of re-authenticating with OCM on every call.
        with create_ocm_workspace_client(
            ocm_connection, self.cache, self.secret_manager, self.settings
        ) as workspace_client:
            current_state, unresolved_clusters, fetch_errors = (
                self._fetch_current_state(
                    workspace_client,
                    clusters,
                    max_workers=self.settings.ocm.groups_fetch_concurrency,
                )
            )
            errors.extend(fetch_errors)

            # A cluster whose current state couldn't be fetched must never
            # look like "no users exist" to the diff below - that would
            # generate spurious add actions for every desired membership on
            # that cluster.  Excluding both sides entirely means no
            # add/delete action is ever computed for it this run.
            if unresolved_clusters:
                current_state = [
                    s for s in current_state if s.cluster not in unresolved_clusters
                ]
                desired = [s for s in desired if s.cluster not in unresolved_clusters]

            # Safeguard: if desired state is empty for a cluster that has
            # current members, a transient GQL error on the client side
            # likely caused the desired list to arrive incomplete.  Treating
            # that as "no users desired" would delete everyone on the
            # cluster — skip it instead and surface an error.
            clusters_with_current = {s.cluster for s in current_state}
            clusters_with_desired = {s.cluster for s in desired}
            empty_desired_clusters = clusters_with_current - clusters_with_desired
            if empty_desired_clusters:
                errors.extend(
                    f"Desired state is empty for cluster {cluster_name} "
                    "which has existing members — refusing to delete all "
                    "memberships (possible upstream data error)"
                    for cluster_name in sorted(empty_desired_clusters)
                )
                current_state = [
                    s for s in current_state if s.cluster not in empty_desired_clusters
                ]

            diff_result = diff_iterables(
                current_state, desired, key=self._diff_key, equal=operator.eq
            )

            for category_actions, category_applied, category_errors in (
                self._process_deletes(
                    workspace_client,
                    diff_result.delete.values(),
                    dry_run=dry_run,
                ),
                self._process_adds(
                    workspace_client,
                    diff_result.add.values(),
                    dry_run=dry_run,
                ),
            ):
                actions.extend(category_actions)
                applied_actions.extend(category_applied)
                errors.extend(category_errors)

        if errors:
            ocm_groups_reconcile_errors.labels(INTEGRATION_NAME, ocm_environment).inc()
        else:
            ocm_groups_reconciled.labels(INTEGRATION_NAME, ocm_environment).inc()

        return OcmGroupsTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
