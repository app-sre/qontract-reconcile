import logging
from collections.abc import Callable, Iterable
from typing import Any

from deepdiff import DeepHash

from reconcile.gql_definitions.cluster_auth_rhidp.clusters import (
    ClusterAuthRHIDPV1,
    ClusterV1,
)
from reconcile.gql_definitions.cluster_auth_rhidp.clusters import query as cluster_query
from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.rhidp.common import (
    AUTH_NAME_LABEL_KEY,
    ISSUER_LABEL_KEY,
    RHIDP_NAMESPACE_LABEL_KEY,
    STATUS_LABEL_KEY,
    StatusValue,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.differ import diff_mappings
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm.clusters import discover_clusters_for_organizations
from reconcile.utils.ocm.label_sources import ClusterRef, LabelState
from reconcile.utils.ocm.labels import add_label, delete_label, update_label
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
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "cluster-auth-rhidp"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class ClusterAuthRhidpIntegrationParams(PydanticRunParams):
    pass


class ManagedLabelConflictError(Exception):
    pass


OcmApis = dict[str, OCMBaseClient]


class ClusterAuthRhidpIntegration(
    QontractReconcileIntegration[ClusterAuthRhidpIntegrationParams]
):
    """Manages the OCM subscription labels for clusters with RHIDP authentication."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(
        self, query_func: Callable | None = None
    ) -> dict[str, Any]:
        """Return the desired state for early exit."""
        if not query_func:
            query_func = gql.get_api().query

        desired = {
            "subs_labels": self.fetch_desired_state(self.get_clusters(query_func)),
        }
        # to figure out wheter to run a PR check of to exit early, a hash value
        # of the desired state is sufficient
        return {"hash": DeepHash(desired).get(desired)}

    def get_clusters(self, query_func: Callable) -> list[ClusterV1]:
        data = cluster_query(query_func)
        return [
            c
            for c in data.clusters or []
            if integration_is_enabled(self.name, c)
            # ocm is mandatory
            and c.ocm
            and c.spec
            and c.spec.q_id
        ]

    def get_environments(self, query_func: Callable) -> list[OCMEnvironment]:
        return ocm_environment_query(query_func).environments

    def fetch_desired_state(self, clusters: Iterable[ClusterV1]) -> LabelState:
        """Fetches the desired state of subscription labels for the given clusters."""
        states: LabelState = {}

        for cluster in clusters:
            assert cluster.ocm and cluster.spec and cluster.spec.q_id  # make mypy happy
            label = {}
            if auth := next(
                (
                    a
                    for a in cluster.auth
                    if isinstance(a, ClusterAuthRHIDPV1) and a.service == "rhidp"
                ),
                None,
            ):
                label = {
                    STATUS_LABEL_KEY: auth.status or StatusValue.ENABLED.value,
                    AUTH_NAME_LABEL_KEY: auth.name,
                }
                if auth.issuer:
                    label[ISSUER_LABEL_KEY] = auth.issuer
            cluster_ref = ClusterRef(
                cluster_id=cluster.spec.q_id,
                org_id=cluster.ocm.org_id,
                ocm_env=cluster.ocm.environment.name,
                name=cluster.name,
                label_container_href=None,
            )
            states[cluster_ref] = label

        return states

    def fetch_current_state(
        self,
        ocm_apis: OcmApis,
        clusters: Iterable[ClusterV1],
        managed_label_prefixes: Iterable[str],
    ) -> LabelState:
        """Fetches the current state of subscription labels for the given clusters.

        If a cluster can't be found in OCM, the resulting dict will not contain a
        state for it, not even an empty one.
        """
        cluster_ids = {c.spec.q_id for c in clusters if c.spec and c.spec.q_id}
        states: LabelState = {}
        for env_name, ocm_api in ocm_apis.items():
            for cluster_details in discover_clusters_for_organizations(
                ocm_api=ocm_api,
                organization_ids=list({
                    c.ocm.org_id
                    for c in clusters
                    if c.ocm and c.ocm.environment.name == env_name
                }),
            ):
                if cluster_details.ocm_cluster.id not in cluster_ids:
                    # there might be more clusters in an organization than we care about
                    continue

                filtered_labels = {
                    label: value
                    for label, value in cluster_details.subscription_labels.get_values_dict().items()
                    if label.startswith(tuple(managed_label_prefixes))
                }
                states[
                    ClusterRef(
                        cluster_id=cluster_details.ocm_cluster.id,
                        org_id=cluster_details.organization_id,
                        ocm_env=env_name,
                        name=cluster_details.ocm_cluster.name,
                        label_container_href=f"{cluster_details.ocm_cluster.subscription.href}/labels",
                    )
                ] = filtered_labels
        return states

    def init_ocm_apis(
        self,
        environments: Iterable[OCMEnvironment],
        init_ocm_base_client: Callable[
            [OCMAPIClientConfigurationProtocol, SecretReaderBase], OCMBaseClient
        ] = init_ocm_base_client,
    ) -> OcmApis:
        """Initialize OCM clients for each OCM environment."""
        return {
            env.name: init_ocm_base_client(env, self.secret_reader)
            for env in environments
        }

    def reconcile(
        self,
        dry_run: bool,
        ocm_apis: OcmApis,
        current_state: LabelState,
        desired_state: LabelState,
    ) -> None:
        # we iterate via the current state because it refers to the clusters we can act on
        for label_owner_ref, current_labels in current_state.items():
            ocm_api = ocm_apis[label_owner_ref.ocm_env]
            desired_labels = desired_state.get(label_owner_ref, {})
            if current_labels == desired_labels:
                continue

            diff_result = diff_mappings(current_labels, desired_labels)

            for label_to_add, value in diff_result.add.items():
                logging.info([
                    "create_label",
                    *label_owner_ref.identity_labels(),
                    f"{label_to_add}={value}",
                ])
                if not dry_run:
                    add_label(
                        ocm_api=ocm_api,
                        label_container_href=label_owner_ref.required_label_container_href(),
                        label=label_to_add,
                        value=value,
                    )
            for label_to_rm, value in diff_result.delete.items():
                logging.info([
                    "delete_label",
                    *label_owner_ref.identity_labels(),
                    f"{label_to_rm}={value}",
                ])
                if not dry_run:
                    delete_label(
                        ocm_api=ocm_api,
                        label_container_href=label_owner_ref.required_label_container_href(),
                        label=label_to_rm,
                    )
            for label_to_update, diff_pair in diff_result.change.items():
                value = diff_pair.desired
                logging.info([
                    "update_label",
                    *label_owner_ref.identity_labels(),
                    f"{label_to_update}={value}",
                ])
                if not dry_run:
                    update_label(
                        ocm_api=ocm_api,
                        label_container_href=label_owner_ref.required_label_container_href(),
                        label=label_to_update,
                        value=value,
                    )

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        clusters = self.get_clusters(gql_api.query)
        environments = self.get_environments(gql_api.query)
        ocm_apis = self.init_ocm_apis(environments, init_ocm_base_client)
        if defer:
            defer(lambda: [ocm_api.close() for ocm_api in ocm_apis.values()])  # type: ignore

        current_state = self.fetch_current_state(
            ocm_apis, clusters, managed_label_prefixes=[RHIDP_NAMESPACE_LABEL_KEY]
        )
        desired_state = self.fetch_desired_state(clusters)
        self.reconcile(
            dry_run=dry_run,
            ocm_apis=ocm_apis,
            current_state=current_state,
            desired_state=desired_state,
        )
