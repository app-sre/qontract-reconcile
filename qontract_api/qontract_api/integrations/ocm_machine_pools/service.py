"""OCM machine pool reconciliation service.

Manages OCM machine pools (OSD / ROSA classic clusters) and node pools (ROSA
HCP clusters). Ported from reconcile/ocm_machine_pools.py for the API context
(ADR-007), following the ocm_groups / ocm_oidc_idp service patterns.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import pydantic
from qontract_utils.differ import DiffPair, diff_mappings
from qontract_utils.ocm_api import (
    OcmMachinePool,
    OcmMachinePoolAutoscaling,
    OcmNodePool,
    OcmNodePoolAutoscaling,
)

from qontract_api.integrations.ocm_machine_pools.domain import (
    ClusterType,
    DesiredMachinePool,
    DesiredNodePool,
)
from qontract_api.integrations.ocm_machine_pools.metrics import (
    INTEGRATION_NAME,
    ocm_machine_pools_reconcile_errors,
    ocm_machine_pools_reconciled,
)
from qontract_api.integrations.ocm_machine_pools.schemas import (
    OcmMachinePoolsAction,
    OcmMachinePoolsActionCreateMachinePool,
    OcmMachinePoolsActionCreateNodePool,
    OcmMachinePoolsActionDeleteMachinePool,
    OcmMachinePoolsActionDeleteNodePool,
    OcmMachinePoolsActionUpdateMachinePool,
    OcmMachinePoolsActionUpdateNodePool,
    OcmMachinePoolsTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.ocm.ocm_client_factory import create_ocm_workspace_client

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.integrations.ocm_machine_pools.domain import (
        DesiredClusterMachinePools,
    )
    from qontract_api.ocm.domain import OcmConnectionParams
    from qontract_api.ocm.ocm_workspace_client import OcmWorkspaceClient
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)

# OSD non-CCS clusters cannot delete their default worker machine pool -
# matches reconcile/utils/ocm/products.py::DEFAULT_OCM_MACHINE_POOL_ID.
DEFAULT_OCM_MACHINE_POOL_ID = "worker"

_DiffKey = tuple[str, str]


def _fetch_pools_for_cluster(
    workspace_client: OcmWorkspaceClient,
    cluster: DesiredClusterMachinePools,
) -> list[OcmMachinePool | OcmNodePool]:
    """Fetch one cluster's live pools, node pools on HCP, machine pools else."""
    if cluster.cluster_type == ClusterType.ROSA_HCP:
        return list(workspace_client.get_node_pools(cluster.cluster_id))
    return list(workspace_client.get_machine_pools(cluster.cluster_id))


class _CurrentPoolState(pydantic.BaseModel):
    """Internal diffing unit: one live pool on a cluster, from OCM."""

    cluster: str
    cluster_id: str
    cluster_type: ClusterType
    pool: OcmMachinePool | OcmNodePool


class _DesiredPoolState(pydantic.BaseModel):
    """Internal diffing unit: one desired pool on a cluster, from the client."""

    cluster: str
    cluster_id: str
    cluster_type: ClusterType
    pool: DesiredMachinePool | DesiredNodePool


def _autoscaling_differs(
    current_min: int,
    current_max: int,
    desired_min: int,
    desired_max: int,
) -> bool:
    """Compare autoscaling bounds."""
    return current_min != desired_min or current_max != desired_max


def _machine_pool_has_diff(
    current: OcmMachinePool, desired: DesiredMachinePool
) -> bool:
    """Whether a live machine pool differs from its desired state."""
    if current.autoscaling is None and desired.autoscaling is None:
        autoscaling_diff = False
    elif current.autoscaling is None or desired.autoscaling is None:
        autoscaling_diff = True
    else:
        autoscaling_diff = _autoscaling_differs(
            current.autoscaling.min_replicas,
            current.autoscaling.max_replicas,
            desired.autoscaling.min_replicas,
            desired.autoscaling.max_replicas,
        )
    return (
        current.replicas != desired.replicas
        or current.taints != desired.taints
        or current.labels != desired.labels
        or current.instance_type != desired.instance_type
        or autoscaling_diff
    )


def _node_pool_has_diff(current: OcmNodePool, desired: DesiredNodePool) -> bool:
    """Whether a live node pool differs from its desired state."""
    if current.autoscaling is None and desired.autoscaling is None:
        autoscaling_diff = False
    elif current.autoscaling is None or desired.autoscaling is None:
        autoscaling_diff = True
    else:
        autoscaling_diff = _autoscaling_differs(
            current.autoscaling.min_replica,
            current.autoscaling.max_replica,
            desired.autoscaling.min_replica,
            desired.autoscaling.max_replica,
        )
    return (
        current.replicas != desired.replicas
        or current.taints != desired.taints
        or current.labels != desired.labels
        or current.aws_node_pool.instance_type != desired.aws_node_pool.instance_type
        or current.subnet != desired.subnet
        or autoscaling_diff
    )


def _states_equal(current: _CurrentPoolState, desired: _DesiredPoolState) -> bool:
    """Diff equality: whether a live pool already matches its desired state."""
    if isinstance(current.pool, OcmNodePool) and isinstance(
        desired.pool, DesiredNodePool
    ):
        return not _node_pool_has_diff(current.pool, desired.pool)
    if isinstance(current.pool, OcmMachinePool) and isinstance(
        desired.pool, DesiredMachinePool
    ):
        return not _machine_pool_has_diff(current.pool, desired.pool)
    # Shape mismatch (e.g. node pool live, machine pool desired) is always a
    # change - _process_changes reports it as an error instead of mutating.
    return False


def _invalid_machine_pool_diff(
    current: OcmMachinePool, desired: DesiredMachinePool
) -> str | None:
    """Fields that cannot be updated on an existing machine pool, if any."""
    if current.instance_type != desired.instance_type:
        return "instance_type"
    return None


def _invalid_node_pool_diff(
    current: OcmNodePool, desired: DesiredNodePool
) -> str | None:
    """Fields that cannot be updated on an existing node pool, if any."""
    if current.aws_node_pool.instance_type != desired.aws_node_pool.instance_type:
        return "instance_type"
    if current.subnet != desired.subnet:
        return "subnet"
    return None


def _labels_or_taints_changed(
    current: OcmMachinePool | OcmNodePool,
    desired: DesiredMachinePool | DesiredNodePool,
) -> bool:
    """Whether the diff includes labels or taints (new nodes only, see log)."""
    return current.labels != desired.labels or current.taints != desired.taints


def _to_wire_machine_pool(desired: DesiredMachinePool) -> OcmMachinePool:
    """Convert a desired machine pool to the Layer 1 wire model."""
    return OcmMachinePool(
        id=desired.id,
        instance_type=desired.instance_type,
        replicas=desired.replicas,
        autoscaling=(
            OcmMachinePoolAutoscaling(
                min_replicas=desired.autoscaling.min_replicas,
                max_replicas=desired.autoscaling.max_replicas,
            )
            if desired.autoscaling
            else None
        ),
        labels=desired.labels,
        taints=desired.taints,
    )


def _to_wire_node_pool(desired: DesiredNodePool) -> OcmNodePool:
    """Convert a desired node pool to the Layer 1 wire model."""
    return OcmNodePool(
        id=desired.id,
        aws_node_pool=desired.aws_node_pool,
        replicas=desired.replicas,
        autoscaling=(
            OcmNodePoolAutoscaling(
                min_replica=desired.autoscaling.min_replica,
                max_replica=desired.autoscaling.max_replica,
            )
            if desired.autoscaling
            else None
        ),
        labels=desired.labels,
        taints=desired.taints,
        subnet=desired.subnet,
    )


class OcmMachinePoolsService:
    """Service for reconciling OCM machine and node pools.

    Fetches current state (live pools per cluster, from OCM), receives
    desired state (from client-side GraphQL), diffs them via ``diff_mappings``
    keyed by (cluster, pool id), and executes create/update/delete actions
    against OCM - preserving every guard the legacy integration had.
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
    def _fetch_current_state(
        workspace_client: OcmWorkspaceClient,
        clusters: list[DesiredClusterMachinePools],
        *,
        max_workers: int,
    ) -> tuple[dict[_DiffKey, _CurrentPoolState], set[str], list[str]]:
        """Fetch live pools for every cluster, concurrently.

        Each cluster's OCM query is an independent HTTP round-trip - fetching
        them serially would make wall-clock time scale linearly with cluster
        count, for no benefit (OcmWorkspaceClient already shares one OcmApi
        connection across threads).  A single cluster's OCM query failing does
        not abort the whole run - it is logged, collected as an error, and
        that cluster is excluded from the diff entirely (unresolved), so a
        read failure can never look like "no pools exist" and generate
        spurious delete actions.

        Returns:
            A tuple of (current_state, unresolved_clusters, errors).
        """
        current_state: dict[_DiffKey, _CurrentPoolState] = {}
        unresolved_clusters: set[str] = set()
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_cluster: dict[
                Future[list[OcmMachinePool | OcmNodePool]],
                DesiredClusterMachinePools,
            ] = {}
            for cluster in clusters:
                future_to_cluster[
                    executor.submit(_fetch_pools_for_cluster, workspace_client, cluster)
                ] = cluster
            for future in as_completed(future_to_cluster):
                cluster = future_to_cluster[future]
                try:
                    pools = future.result()
                except Exception as e:
                    message = (
                        f"Failed to fetch pools for cluster "
                        f"{cluster.name}; skipping for this reconcile: {e}"
                    )
                    logger.exception(message)
                    errors.append(message)
                    unresolved_clusters.add(cluster.name)
                    continue
                for pool in pools:
                    current_state[cluster.name, pool.id] = _CurrentPoolState(
                        cluster=cluster.name,
                        cluster_id=cluster.cluster_id,
                        cluster_type=cluster.cluster_type,
                        pool=pool,
                    )
        return current_state, unresolved_clusters, errors

    @staticmethod
    def _build_desired_state(
        clusters: list[DesiredClusterMachinePools],
    ) -> dict[_DiffKey, _DesiredPoolState]:
        """Build the desired state keyed by (cluster, pool id)."""
        desired_state: dict[_DiffKey, _DesiredPoolState] = {}
        for cluster in clusters:
            for pool in cluster.pools:
                desired_state[cluster.name, pool.id] = _DesiredPoolState(
                    cluster=cluster.name,
                    cluster_id=cluster.cluster_id,
                    cluster_type=cluster.cluster_type,
                    pool=pool,
                )
        return desired_state

    @staticmethod
    def _process_adds(
        workspace_client: OcmWorkspaceClient,
        add_states: dict[_DiffKey, _DesiredPoolState],
        *,
        dry_run: bool,
    ) -> tuple[
        list[OcmMachinePoolsAction],
        list[OcmMachinePoolsAction],
        list[str],
        set[str],
    ]:
        """Process create actions (pools that should exist but don't).

        Returns (actions, applied, errors, failed_clusters). failed_clusters
        names clusters where a create failed - the caller must skip those
        clusters' deletes, so a failed pool replacement can never leave a
        cluster with zero pools (the legacy integration ordered creates
        before deletes for the same reason).
        """
        actions: list[OcmMachinePoolsAction] = []
        applied: list[OcmMachinePoolsAction] = []
        errors: list[str] = []
        failed_clusters: set[str] = set()

        for state in add_states.values():
            if isinstance(state.pool, DesiredNodePool):
                action: OcmMachinePoolsAction = OcmMachinePoolsActionCreateNodePool(
                    cluster=state.cluster, pool_id=state.pool.id
                )
            else:
                action = OcmMachinePoolsActionCreateMachinePool(
                    cluster=state.cluster, pool_id=state.pool.id
                )
            actions.append(action)
            if dry_run:
                continue
            try:
                if isinstance(state.pool, DesiredNodePool):
                    workspace_client.create_node_pool(
                        state.cluster_id, _to_wire_node_pool(state.pool)
                    )
                else:
                    workspace_client.create_machine_pool(
                        state.cluster_id, _to_wire_machine_pool(state.pool)
                    )
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{state.cluster}: failed to create pool {state.pool.id}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)
                failed_clusters.add(state.cluster)

        return actions, applied, errors, failed_clusters

    @staticmethod
    def _process_changes(
        workspace_client: OcmWorkspaceClient,
        change_pairs: dict[_DiffKey, DiffPair[_CurrentPoolState, _DesiredPoolState]],
        *,
        dry_run: bool,
    ) -> tuple[list[OcmMachinePoolsAction], list[OcmMachinePoolsAction], list[str]]:
        """Process update actions (pools that exist but differ).

        Immutable-field diffs (instance_type, subnet) become errors, never
        mutations - preserving the legacy InvalidUpdateError behavior.
        """
        actions: list[OcmMachinePoolsAction] = []
        applied: list[OcmMachinePoolsAction] = []
        errors: list[str] = []

        for (cluster_name, _), diff_pair in change_pairs.items():
            current, desired = diff_pair.current, diff_pair.desired
            action: OcmMachinePoolsAction
            wire_pool: OcmMachinePool | OcmNodePool
            if isinstance(current.pool, OcmNodePool) and isinstance(
                desired.pool, DesiredNodePool
            ):
                invalid_diff = _invalid_node_pool_diff(current.pool, desired.pool)
                action = OcmMachinePoolsActionUpdateNodePool(
                    cluster=cluster_name, pool_id=desired.pool.id
                )
                wire_pool = _to_wire_node_pool(desired.pool)
            elif isinstance(current.pool, OcmMachinePool) and isinstance(
                desired.pool, DesiredMachinePool
            ):
                invalid_diff = _invalid_machine_pool_diff(current.pool, desired.pool)
                action = OcmMachinePoolsActionUpdateMachinePool(
                    cluster=cluster_name, pool_id=desired.pool.id
                )
                wire_pool = _to_wire_machine_pool(desired.pool)
            else:
                errors.append(
                    f"{cluster_name}: pool shape mismatch between current "
                    f"and desired state for pool {desired.pool.id}"
                )
                continue

            # Legacy parity: the warning fires whenever labels/taints differ,
            # even when an immutable-field diff turns the update into an error.
            if _labels_or_taints_changed(current.pool, desired.pool):
                logger.warning(
                    f"updating labels or taints for pool {desired.pool.id} "
                    f"on cluster {cluster_name} will only be applied to "
                    f"new Nodes"
                )

            if invalid_diff:
                errors.append(
                    f"can not update {invalid_diff} for existing pool on "
                    f"cluster {cluster_name}, CURRENT: "
                    f"{current.pool.model_dump_json()}, DESIRED: "
                    f"{desired.pool.model_dump_json()}"
                )
                continue

            actions.append(action)
            if dry_run:
                continue
            try:
                if isinstance(wire_pool, OcmNodePool):
                    workspace_client.update_node_pool(desired.cluster_id, wire_pool)
                else:
                    workspace_client.update_machine_pool(desired.cluster_id, wire_pool)
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{cluster_name}: failed to update pool {desired.pool.id}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)

        return actions, applied, errors

    @staticmethod
    def _process_deletes(
        workspace_client: OcmWorkspaceClient,
        delete_states: dict[_DiffKey, _CurrentPoolState],
        desired_state: dict[_DiffKey, _DesiredPoolState],
        *,
        dry_run: bool,
        blocked_clusters: set[str],
    ) -> tuple[list[OcmMachinePoolsAction], list[OcmMachinePoolsAction], list[str]]:
        """Process delete actions (pools that exist but shouldn't).

        Preserves the legacy delete guards: a cluster must keep at least one
        pool, and OSD clusters cannot delete their default worker pool.
        Deletes for clusters in blocked_clusters (a pool create failed there
        this run) are skipped, so a failed replacement can never leave a
        cluster with zero pools.
        """
        actions: list[OcmMachinePoolsAction] = []
        applied: list[OcmMachinePoolsAction] = []
        errors: list[str] = []

        desired_clusters = {state.cluster for state in desired_state.values()}

        for (cluster_name, _), state in delete_states.items():
            if cluster_name in blocked_clusters:
                errors.append(
                    f"skipping deletion of pool {state.pool.id} on cluster "
                    f"{cluster_name}: a pool creation failed on this cluster "
                    f"this run, refusing to leave the cluster without pools"
                )
                continue
            if cluster_name not in desired_clusters:
                errors.append(
                    f"can not delete all machine pools for cluster {cluster_name}"
                )
                continue
            if (
                state.cluster_type == ClusterType.OSD
                and isinstance(state.pool, OcmMachinePool)
                and state.pool.id == DEFAULT_OCM_MACHINE_POOL_ID
            ):
                errors.append(
                    f"can not delete machine pool {state.pool.id} for "
                    f"cluster {cluster_name}"
                )
                continue

            action: OcmMachinePoolsAction
            if isinstance(state.pool, OcmNodePool):
                action = OcmMachinePoolsActionDeleteNodePool(
                    cluster=cluster_name, pool_id=state.pool.id
                )
            else:
                action = OcmMachinePoolsActionDeleteMachinePool(
                    cluster=cluster_name, pool_id=state.pool.id
                )
            actions.append(action)
            if dry_run:
                continue
            try:
                if isinstance(state.pool, OcmNodePool):
                    workspace_client.delete_node_pool(state.cluster_id, state.pool.id)
                else:
                    workspace_client.delete_machine_pool(
                        state.cluster_id, state.pool.id
                    )
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{cluster_name}: failed to delete pool {state.pool.id}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)

        return actions, applied, errors

    def reconcile(
        self,
        ocm_environment: str,
        ocm_connection: OcmConnectionParams,
        clusters: list[DesiredClusterMachinePools],
        *,
        dry_run: bool = True,
    ) -> OcmMachinePoolsTaskResult:
        """Reconcile OCM machine/node pools for one OCM environment."""
        desired_state = self._build_desired_state(clusters)

        actions: list[OcmMachinePoolsAction] = []
        applied_actions: list[OcmMachinePoolsAction] = []
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
                    max_workers=self.settings.ocm.machine_pools_fetch_concurrency,
                )
            )
            errors.extend(fetch_errors)

            # A cluster whose current state couldn't be fetched must never
            # look like "no pools exist" to the diff below - that would
            # generate spurious delete actions for every live pool on it.
            # Excluding both sides entirely means no action is ever computed
            # for it this run.
            if unresolved_clusters:
                current_state = {
                    k: v
                    for k, v in current_state.items()
                    if v.cluster not in unresolved_clusters
                }
                desired_state = {
                    k: v
                    for k, v in desired_state.items()
                    if v.cluster not in unresolved_clusters
                }

            diff_result = diff_mappings(
                current_state,
                desired_state,
                equal=_states_equal,
            )

            # Legacy ordering: creates are processed BEFORE deletes, and a
            # cluster whose create failed has its deletes skipped - a failed
            # pool replacement (delete old + create new) must never leave a
            # cluster with zero pools.
            add_result = self._process_adds(
                workspace_client,
                diff_result.add,
                dry_run=dry_run,
            )
            change_result = self._process_changes(
                workspace_client,
                diff_result.change,
                dry_run=dry_run,
            )
            delete_result = self._process_deletes(
                workspace_client,
                diff_result.delete,
                desired_state,
                dry_run=dry_run,
                blocked_clusters=add_result[3],
            )
            for category_actions, category_applied, category_errors in (
                add_result[:3],
                change_result,
                delete_result,
            ):
                actions.extend(category_actions)
                applied_actions.extend(category_applied)
                errors.extend(category_errors)

        if errors:
            ocm_machine_pools_reconcile_errors.labels(
                INTEGRATION_NAME, ocm_environment
            ).inc()
        else:
            ocm_machine_pools_reconciled.labels(INTEGRATION_NAME, ocm_environment).inc()

        return OcmMachinePoolsTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
