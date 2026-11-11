"""OCM machine pools reconciliation via qontract-api.

This is the client-side integration that calls qontract-api instead of
directly managing OCM machine pools / node pools.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).

Key differences from reconcile/ocm_machine_pools.py:
- Suffix '_api' indicates API-based integration
- GraphQL queries for desired state happen client-side here
- Business logic (reconciliation) happens server-side (qontract-api)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from qontract_api_client.client import ocm_machine_pools as reconcile_ocm_machine_pools
from qontract_api_client.schemas import (
    DesiredClusterMachinePools,
    DesiredMachinePool,
    DesiredMachinePoolAutoscaling,
    DesiredNodePool,
    DesiredNodePoolAutoscaling,
    OcmConnectionParams,
    OcmMachinePoolsReconcileRequest,
    OcmMachinePoolsTaskResponse,
    OcmMachinePoolsTaskResult,
    OcmNodePoolAws,
    OcmTaint,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.ocm_machine_pools_api.clusters import (
    ClusterV1,
)
from reconcile.gql_definitions.ocm_machine_pools_api.clusters import (
    query as clusters_query,
)
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from reconcile.gql_definitions.ocm_machine_pools_api.clusters import (
        ClusterMachinePoolV1,
    )

QONTRACT_INTEGRATION = "ocm-machine-pools-api"


def _get_clusters() -> list[ClusterV1]:
    """Fetch clusters with machine pool definitions from App-Interface GraphQL."""
    gqlapi = gql.get_api()
    data = clusters_query(gqlapi.query)
    return data.clusters or []


def _classify_cluster_type(cluster: ClusterV1) -> str:
    """Map the cluster product to the server-side cluster type value.

    Mirrors the legacy integration's _classify_cluster_type: rosa + hypershift
    means ROSA HCP (node pools), everything else machine pools.
    """
    if cluster.spec is None:
        raise IntegrationError(
            f"ocm-machine-pools-api: cluster {cluster.name} is missing spec"
        )
    match cluster.spec.product:
        case "osd":
            return "osd"
        case "rosa":
            return "hypershift" if cluster.spec.hypershift else "rosa"
        case _:
            raise IntegrationError(
                f"ocm-machine-pools-api: unknown cluster type for cluster "
                f"{cluster.name} (product={cluster.spec.product})"
            )


def _build_desired_machine_pool(
    pool: ClusterMachinePoolV1,
) -> DesiredMachinePool:
    """Convert a GQL machine pool to the API's desired-state model."""
    return DesiredMachinePool(
        id=pool.q_id,
        instance_type=pool.instance_type,
        replicas=pool.replicas,
        autoscaling=(
            DesiredMachinePoolAutoscaling(
                min_replicas=pool.autoscale.min_replicas,
                max_replicas=pool.autoscale.max_replicas,
            )
            if pool.autoscale
            else None
        ),
        labels=pool.labels,
        taints=_build_taints(pool),
    )


def _build_desired_node_pool(pool: ClusterMachinePoolV1) -> DesiredNodePool:
    """Convert a GQL node pool to the API's desired-state model (HCP shape)."""
    return DesiredNodePool(
        id=pool.q_id,
        aws_node_pool=OcmNodePoolAws(instance_type=pool.instance_type),
        subnet=pool.subnet,
        replicas=pool.replicas,
        autoscaling=(
            # HyperShift node pools use the singular field names
            DesiredNodePoolAutoscaling(
                min_replica=pool.autoscale.min_replicas,
                max_replica=pool.autoscale.max_replicas,
            )
            if pool.autoscale
            else None
        ),
        labels=pool.labels,
        taints=_build_taints(pool),
    )


def _build_taints(pool: ClusterMachinePoolV1) -> list[OcmTaint] | None:
    """Convert GQL taints to the wire model, preserving absence."""
    if pool.taints is None:
        return None
    return [OcmTaint(key=t.key, value=t.value, effect=t.effect) for t in pool.taints]


def _build_api_clusters(
    clusters: list[ClusterV1],
) -> list[DesiredClusterMachinePools]:
    """Build API cluster objects with desired pools from typed GQL data."""
    api_clusters: list[DesiredClusterMachinePools] = []
    for cluster in clusters:
        if cluster.spec is None:
            # Legacy parity: a cluster with pools but no spec fails the run
            # instead of being silently skipped.
            raise IntegrationError(
                f"ocm-machine-pools-api: cluster {cluster.name} is missing spec"
            )
        if not (spec_id := cluster.spec.q_id):
            logging.warning(
                f"ocm-machine-pools-api: cluster {cluster.name} has no spec.id, "
                f"skipping"
            )
            continue
        cluster_type = _classify_cluster_type(cluster)
        pools = cluster.machine_pools or []
        desired_pools: list[DesiredMachinePool | DesiredNodePool]
        if cluster_type == "hypershift":
            desired_pools = [_build_desired_node_pool(p) for p in pools]
        else:
            desired_pools = [_build_desired_machine_pool(p) for p in pools]
        api_clusters.append(
            DesiredClusterMachinePools(
                name=cluster.name,
                cluster_id=spec_id,
                cluster_type=cluster_type,
                pools=desired_pools,
            )
        )
    return api_clusters


def _group_clusters_by_ocm(
    clusters: list[ClusterV1],
) -> dict[tuple[str, str], list[ClusterV1]]:
    """Group clusters by (OCM environment name, OCM instance name).

    Legacy parity: OCMMap keyed one OCM client per instance name, so
    clusters whose OCM config overrides differ (different instances in the
    same environment) reconcile with their own connection instead of
    borrowing the first cluster's credentials.
    """
    groups: dict[tuple[str, str], list[ClusterV1]] = defaultdict(list)
    for cluster in clusters:
        if (ocm := cluster.ocm) is not None and ocm.environment is not None:
            groups[ocm.environment.name, ocm.name].append(cluster)
    return groups


def _build_ocm_connection(
    cluster: ClusterV1,
    secret_manager_url: str,
) -> OcmConnectionParams:
    """Build OCM connection params from the cluster's OCM config and environment."""
    ocm = cluster.ocm
    assert ocm is not None  # caller guarantees OCM config exists
    env = ocm.environment
    assert env is not None

    client_id = ocm.access_token_client_id or env.access_token_client_id
    access_token_url = ocm.access_token_url or env.access_token_url
    token_secret = (
        ocm.access_token_client_secret
        if ocm.access_token_client_secret is not None
        else env.access_token_client_secret
    )
    if not token_secret.path or not client_id or not env.name:
        raise IntegrationError(
            f"ocm-machine-pools-api: required OCM credentials "
            f"missing from cluster OCM configuration (env={env.name})"
        )

    return OcmConnectionParams(
        secret_manager_url=secret_manager_url,
        path=token_secret.path,
        field=token_secret.field,
        version=token_secret.version,
        ocm_url=env.url,
        access_token_url=access_token_url,
        access_token_client_id=client_id,
    )


class OcmMachinePoolsIntegrationParams(PydanticRunParams):
    """Parameters for ocm-machine-pools-api integration."""


class OcmMachinePoolsIntegration(
    QontractReconcileApiIntegration[OcmMachinePoolsIntegrationParams]
):
    """Manage OCM machine pools / node pools via qontract-api.

    This integration:
    1. Queries App-Interface for clusters with OCM and machinePools definitions
    2. Classifies each cluster (OSD / ROSA classic / ROSA HCP) and builds the
       desired pool state client-side (ADR-002)
    3. Groups clusters by OCM environment and sends one request per
       environment to qontract-api for reconciliation
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def _reconcile_env(
        self,
        clusters: list[DesiredClusterMachinePools],
        ocm_connection: OcmConnectionParams,
        ocm_environment: str,
        dry_run: bool,
    ) -> OcmMachinePoolsTaskResponse:
        """Send desired state for one OCM environment to qontract-api."""
        request = OcmMachinePoolsReconcileRequest(
            ocm_environment=ocm_environment,
            ocm_connection=ocm_connection,
            clusters=clusters,
            dry_run=dry_run,
        )
        with self.log_api_exceptions():
            response = await reconcile_ocm_machine_pools(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        all_clusters = _get_clusters()
        if not all_clusters:
            logging.debug("No clusters found in app-interface")
            return

        # Filter for clusters the integration is enabled on and that have
        # both OCM config and machine pool definitions (legacy parity).
        clusters = [
            c
            for c in all_clusters
            if integration_is_enabled(QONTRACT_INTEGRATION, c)
            and c.ocm is not None
            and c.machine_pools is not None
        ]
        if not clusters:
            logging.debug(
                "No clusters with machine pool definitions found with "
                "integration enabled"
            )
            return

        for (env_name, _ocm_name), env_cluster_list in _group_clusters_by_ocm(
            clusters
        ).items():
            api_clusters = _build_api_clusters(env_cluster_list)
            if not api_clusters:
                continue

            # Build the OCM connection from the first cluster's OCM config
            # (all clusters in a group share the same OCM instance and
            # therefore its credentials).
            ocm_connection = _build_ocm_connection(
                env_cluster_list[0], self.secret_manager_url
            )

            task = await self._reconcile_env(
                clusters=api_clusters,
                ocm_connection=ocm_connection,
                ocm_environment=env_name,
                dry_run=dry_run,
            )

            # Wait for task completion and log actions (both dry-run and
            # non-dry-run - server-side errors must always be surfaced).
            task_result = await self.poll_task_status(
                status_url=task.status_url, result_type=OcmMachinePoolsTaskResult
            )
            if task_result.status == TaskStatus.PENDING:
                raise IntegrationError(
                    f"ocm-machine-pools-api: task for env {env_name} did not "
                    "complete within the timeout period"
                )

            for action in task_result.actions or []:
                logging.info(
                    f"{action.action_type=} {action.cluster=} {action.pool_id=}"
                )

            errors = task_result.errors or []
            if errors or task_result.status != TaskStatus.SUCCESS:
                raise IntegrationError(
                    f"ocm-machine-pools-api: task for env {env_name} ended "
                    f"with status {task_result.status.value}; {len(errors)} "
                    f"error(s): {'; '.join(errors)}"
                )
