from __future__ import annotations

import logging
from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    validator,
)

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.ocm_subscription_labels.clusters import ClusterV1
from reconcile.gql_definitions.ocm_subscription_labels.clusters import (
    query as cluster_query,
)
from reconcile.utils import gql
from reconcile.utils.differ import diff_mappings
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.helpers import flatten
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_for_organizations,
)
from reconcile.utils.ocm.labels import (
    add_subscription_label,
    delete_ocm_label,
    update_ocm_label,
)
from reconcile.utils.ocm_base_client import (
    OCMAPIClientConfigurationProtocol,
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import SecretReaderBase

QONTRACT_INTEGRATION = "ocm-subscription-labels"


class EnvWithClusters(BaseModel):
    env: OCMEnvironment
    clusters: list[ClusterV1] = []

    class Config:
        arbitrary_types_allowed = True


class ClusterLabelState(BaseModel):
    env: OCMEnvironment
    ocm_api: OCMBaseClient
    cluster_details: Optional[ClusterDetails] = None
    labels: dict[str, str] = {}

    class Config:
        arbitrary_types_allowed = True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ClusterLabelState):
            raise NotImplementedError("Cannot compare to non ClusterState objects.")
        return self.labels == other.labels


ClusterStates = dict[str, ClusterLabelState]


class OcmLabelsIntegrationParams(PydanticRunParams):
    managed_label_prefixes: list[str] = []

    @validator("managed_label_prefixes")
    def must_end_with_dot(  # pylint: disable=no-self-argument
        cls, v: list[str]
    ) -> list[str]:
        return [prefix + "." if not prefix.endswith(".") else prefix for prefix in v]


class OcmLabelsIntegration(QontractReconcileIntegration[OcmLabelsIntegrationParams]):
    """Sync cluster.ocm-labels to OCM."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_clusters(self, query_func: Callable) -> list[ClusterV1]:
        data = cluster_query(query_func)
        return [
            c
            for c in data.clusters or []
            if c.ocm is not None and integration_is_enabled(self.name, c)
        ]

    def get_ocm_environments(
        self,
        clusters: Iterable[ClusterV1],
    ) -> list[EnvWithClusters]:
        envs: dict[str, EnvWithClusters] = {}

        for cluster in clusters:
            if cluster.ocm is None:
                # already filtered out in get_clusters - make mypy happy
                continue
            if cluster.ocm.environment.name not in envs:
                envs[cluster.ocm.environment.name] = EnvWithClusters(
                    env=cluster.ocm.environment, clusters=[cluster]
                )
            else:
                envs[cluster.ocm.environment.name].clusters.append(cluster)

        return list(envs.values())

    def init_ocm_apis(
        self,
        envs: Iterable[EnvWithClusters],
        init_ocm_base_client: Callable[
            [OCMAPIClientConfigurationProtocol, SecretReaderBase], OCMBaseClient
        ] = init_ocm_base_client,
    ) -> None:
        self.ocm_apis = {
            env.env.name: init_ocm_base_client(env.env, self.secret_reader)
            for env in envs
        }

    def get_early_exit_desired_state(self) -> Optional[dict[str, Any]]:
        gqlapi = gql.get_api()
        return {"clusters": [c.dict() for c in self.get_clusters(gqlapi.query)]}

    def run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()
        clusters = self.get_clusters(gqlapi.query)
        current_state = self.fetch_current_state(
            clusters, self.params.managed_label_prefixes
        )
        desired_state = self.fetch_desired_state(clusters)
        self.reconcile(dry_run, current_state, desired_state)

    def fetch_current_state(
        self, clusters: Iterable[ClusterV1], managed_label_prefixes: list[str]
    ) -> ClusterStates:
        states: ClusterStates = {}
        envs = self.get_ocm_environments(clusters)
        self.init_ocm_apis(envs)
        for env in envs:
            for cluster_details in discover_clusters_for_organizations(
                ocm_api=self.ocm_apis[env.env.name],
                organization_ids=list({c.ocm.org_id for c in clusters if c.ocm}),
            ):
                filtered_labels = {
                    label: value
                    for label, value in cluster_details.subscription_labels.get_values_dict().items()
                    if label.startswith(tuple(managed_label_prefixes))
                }
                states[cluster_details.ocm_cluster.name] = ClusterLabelState(
                    env=env.env,
                    ocm_api=self.ocm_apis[env.env.name],
                    cluster_details=cluster_details,
                    labels=filtered_labels,
                )
        return states

    def fetch_desired_state(self, clusters: Iterable[ClusterV1]) -> ClusterStates:
        states: ClusterStates = {}
        for cluster in clusters:
            if cluster.ocm is None:
                # already filtered out in get_clusters - make mypy happy
                continue
            states[cluster.name] = ClusterLabelState(
                env=cluster.ocm.environment,
                ocm_api=self.ocm_apis[cluster.ocm.environment.name],
                labels=flatten(cluster.ocm_subscription_labels or {}),
            )

        return states

    def reconcile(
        self,
        dry_run: bool,
        current_cluster_states: ClusterStates,
        desired_cluster_states: ClusterStates,
    ) -> None:
        for cluster_name, desired_cluster_state in desired_cluster_states.items():
            try:
                current_cluster_state = current_cluster_states[cluster_name]
                if not (cluster_details := current_cluster_state.cluster_details):
                    # this should never happen - make mypy happy
                    raise RuntimeError("Cluster details not found.")

                if desired_cluster_state == current_cluster_state:
                    continue
            except KeyError:
                logging.info(
                    f"Cluster '{cluster_name}' not found in OCM. Maybe it doesn't exist yet. Skipping."
                )
                continue

            diff_result = diff_mappings(
                current_cluster_state.labels, desired_cluster_state.labels
            )

            for label_to_add, value in diff_result.add.items():
                logging.info(
                    [
                        "create_cluster_subscription_label",
                        cluster_name,
                        f"{label_to_add}={value}",
                    ]
                )
                if not dry_run:
                    add_subscription_label(
                        ocm_api=desired_cluster_state.ocm_api,
                        ocm_cluster=cluster_details.ocm_cluster,
                        label=label_to_add,
                        value=value,
                    )
            for label_to_rm, value in diff_result.delete.items():
                logging.info(
                    [
                        "delete_cluster_subscription_label",
                        cluster_name,
                        f"{label_to_rm}={value}",
                    ]
                )
                if not dry_run:
                    delete_ocm_label(
                        ocm_api=desired_cluster_state.ocm_api,
                        ocm_label=cluster_details.labels[label_to_rm],
                    )
            for label_to_update, diff_pair in diff_result.change.items():
                value = diff_pair.desired
                logging.info(
                    [
                        "update_cluster_subscription_label",
                        cluster_name,
                        f"{label_to_update}={value}",
                    ]
                )
                if not dry_run:
                    update_ocm_label(
                        ocm_api=desired_cluster_state.ocm_api,
                        ocm_label=cluster_details.labels[label_to_update],
                        value=value,
                    )
