"""OCM groups reconciliation via qontract-api.

This is the client-side integration that calls qontract-api instead of
directly managing OCM cluster group memberships.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).

Key differences from reconcile/ocm_groups.py:
- Suffix '_api' indicates API-based integration
- GraphQL queries for desired state happen client-side here
- Business logic (reconciliation) happens server-side (qontract-api)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from qontract_api_client.client import ocm_groups as reconcile_ocm_groups
from qontract_api_client.schemas import (
    OcmConnectionParams,
    OcmGroupsCluster,
    OcmGroupsReconcileRequest,
    OcmGroupsTaskResponse,
    OcmGroupsTaskResult,
    OcmGroupUser,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

import reconcile.openshift_base as ob
from reconcile.gql_definitions.ocm_groups_api.clusters import (
    ClusterV1,
)
from reconcile.gql_definitions.ocm_groups_api.clusters import (
    query as clusters_query,
)
from reconcile.gql_definitions.ocm_groups_api.roles import (
    query as roles_query,
)
from reconcile.utils import expiration, gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment

QONTRACT_INTEGRATION = "ocm-groups-api"
VALID_OCM_GROUPS = frozenset({"dedicated-admins", "cluster-admins"})


class OcmGroupsIntegrationParams(PydanticRunParams):
    """Parameters for ocm-groups-api integration."""


def _get_clusters() -> list[ClusterV1]:
    """Fetch clusters with OCM config from App-Interface GraphQL."""
    gqlapi = gql.get_api()
    data = clusters_query(gqlapi.query)
    return data.clusters or []


def _fetch_desired_state(cluster_names: list[str]) -> list[OcmGroupUser]:
    """Fetch desired group memberships from roles (client-side per ADR-002).

    Mirrors reconcile/openshift_groups.fetch_desired_state but uses the
    dedicated ocm_groups_api roles query.
    """
    gqlapi = gql.get_api()
    data = roles_query(gqlapi.query)
    roles = expiration.filter(data.roles or [])
    desired_state: list[OcmGroupUser] = []

    for r in roles:
        for a in r.access or []:
            if not a.cluster or not a.group:
                continue
            if a.cluster.name not in cluster_names:
                continue

            user_keys = ob.determine_user_keys_for_access(
                a.cluster.name,
                a.cluster.auth,
            )
            for u in r.users:
                for user_key in user_keys:
                    if (username := getattr(u, user_key, None)) is None:
                        continue
                    desired_state.append(
                        OcmGroupUser(
                            cluster=a.cluster.name,
                            group=a.group,
                            user=username,
                        )
                    )

    return desired_state


def _build_api_clusters(
    clusters: list[ClusterV1],
) -> list[OcmGroupsCluster]:
    """Build API cluster objects from typed GQL cluster data."""
    api_clusters: list[OcmGroupsCluster] = []
    for c in clusters:
        managed_groups = [g for g in (c.managed_groups or []) if g in VALID_OCM_GROUPS]
        if not managed_groups:
            continue
        if not (spec_id := c.spec.q_id if c.spec else None):
            logging.warning(f"Cluster {c.name} has no spec.id, skipping")
            continue
        api_clusters.append(
            OcmGroupsCluster(
                name=c.name,
                cluster_id=spec_id,
                managed_groups=managed_groups,
            )
        )
    return api_clusters


def _group_clusters_by_ocm_env(
    clusters: list[ClusterV1],
) -> dict[str, list[ClusterV1]]:
    """Group clusters by their OCM environment name.

    Clusters without OCM config are silently skipped.
    """
    env_clusters: dict[str, list[ClusterV1]] = defaultdict(list)
    for c in clusters:
        if (ocm := c.ocm) is not None and ocm.environment is not None:
            env_clusters[ocm.environment.name].append(c)
    return env_clusters


def _build_ocm_connection(
    ocm_env: OCMEnvironment,
    ocm_config: ClusterV1,
    secret_manager_url: str,
) -> OcmConnectionParams:
    """Build OCM connection params from the cluster's OCM config and environment."""
    ocm = ocm_config.ocm
    assert ocm is not None  # caller guarantees OCM config exists
    env = ocm.environment

    client_id = ocm.access_token_client_id or env.access_token_client_id
    access_token_url = ocm.access_token_url or env.access_token_url
    if (
        not (
            token_secret := ocm.access_token_client_secret
            or env.access_token_client_secret
        )
        or not token_secret.path
        or not client_id
        or not env.name
    ):
        raise IntegrationError(
            f"ocm-groups-api: required OCM credentials "
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


class OcmGroupsIntegration(QontractReconcileApiIntegration[OcmGroupsIntegrationParams]):
    """Manage OCM cluster group memberships via qontract-api.

    This integration:
    1. Queries App-Interface for clusters with OCM and managedGroups
    2. Queries App-Interface for role-based group memberships (desired state)
    3. Groups clusters by OCM environment and sends one request per environment
       to qontract-api for reconciliation
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def _reconcile_env(
        self,
        clusters: list[OcmGroupsCluster],
        desired_state: list[OcmGroupUser],
        ocm_connection: OcmConnectionParams,
        ocm_environment: str,
        dry_run: bool,
    ) -> OcmGroupsTaskResponse:
        """Send desired state for one OCM environment to qontract-api."""
        request = OcmGroupsReconcileRequest(
            ocm_environment=ocm_environment,
            ocm_connection=ocm_connection,
            clusters=clusters,
            desired_state=desired_state,
            dry_run=dry_run,
        )
        with self.log_api_exceptions():
            response = await reconcile_ocm_groups(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        all_clusters = _get_clusters()
        if not all_clusters:
            logging.debug("No clusters found in app-interface")
            return

        # Filter for OCM-compatible clusters with integration enabled
        clusters = [
            c
            for c in all_clusters
            if integration_is_enabled(QONTRACT_INTEGRATION, c) and c.ocm is not None
        ]
        if not clusters:
            logging.debug("No OCM-compatible clusters found with integration enabled")
            return

        cluster_names = [c.name for c in clusters]

        # Fetch desired state from GraphQL (client-side per ADR-002)
        desired_state_all = [
            ds
            for ds in _fetch_desired_state(cluster_names=cluster_names)
            if ds.group in VALID_OCM_GROUPS
        ]

        # Group clusters by OCM environment
        env_clusters = _group_clusters_by_ocm_env(clusters)

        for env_name, env_cluster_list in env_clusters.items():
            if not (api_clusters := _build_api_clusters(env_cluster_list)):
                logging.debug(
                    f"No clusters with OCM-valid managed groups for env {env_name}"
                )
                continue

            # Filter desired state to only clusters in this environment
            env_cluster_names = {c.name for c in env_cluster_list}
            desired_state = [
                d for d in desired_state_all if d.cluster in env_cluster_names
            ]

            # Build OCM connection from the first cluster's OCM config
            first_cluster = env_cluster_list[0]
            ocm = first_cluster.ocm
            assert ocm is not None  # filtered above

            ocm_connection = _build_ocm_connection(
                ocm.environment, first_cluster, self.secret_manager_url
            )

            task = await self._reconcile_env(
                clusters=api_clusters,
                desired_state=desired_state,
                ocm_connection=ocm_connection,
                ocm_environment=env_name,
                dry_run=dry_run,
            )

            # Wait for task completion and log actions (both dry-run and
            # non-dry-run - server-side errors must always be surfaced).
            task_result = await self.poll_task_status(
                status_url=task.status_url, result_type=OcmGroupsTaskResult
            )
            if task_result.status == TaskStatus.PENDING:
                raise IntegrationError(
                    f"ocm-groups-api: task for env {env_name} did not complete "
                    "within the timeout period"
                )

            for action in task_result.actions or []:
                logging.info(
                    f"{action.action_type=} {action.cluster=} "
                    f"{action.group=} {action.user=}"
                )

            if errors_summary := "; ".join(task_result.errors or []):
                raise IntegrationError(
                    f"ocm-groups-api: {len(task_result.errors)} error(s) "
                    f"in env {env_name}: {errors_summary}"
                )
