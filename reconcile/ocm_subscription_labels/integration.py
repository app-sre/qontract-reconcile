from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Any,
    Optional,
)

from reconcile.aus.aus_label_source import (
    init_aus_cluster_label_source,
    init_aus_org_label_source,
)
from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.ocm_subscription_labels.clusters import ClusterV1
from reconcile.gql_definitions.ocm_subscription_labels.clusters import (
    query as cluster_query,
)
from reconcile.gql_definitions.ocm_subscription_labels.organizations import (
    OpenShiftClusterManagerV1,
)
from reconcile.gql_definitions.ocm_subscription_labels.organizations import (
    query as organization_query,
)
from reconcile.ocm_subscription_labels.label_sources import (
    ClusterRef,
    LabelOwnerRef,
    LabelSource,
    OrgRef,
)
from reconcile.utils import gql
from reconcile.utils.differ import diff_mappings
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.helpers import flatten
from reconcile.utils.ocm.clusters import discover_clusters_for_organizations
from reconcile.utils.ocm.labels import (
    add_label,
    build_organization_labels_href,
    delete_label,
    get_org_labels,
    update_label,
)
from reconcile.utils.ocm.search_filters import Filter
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


class OcmLabelsIntegrationParams(PydanticRunParams):
    managed_label_prefixes: list[str] = []


class ManagedLabelPrefixConflictError(Exception):
    pass


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

    def get_organizations(
        self, query_func: Callable
    ) -> list[OpenShiftClusterManagerV1]:
        return organization_query(query_func).organizations or []

    def get_environments(self, query_func: Callable) -> list[OCMEnvironment]:
        return ocm_environment_query(query_func).environments

    def init_ocm_apis(
        self,
        environments: Iterable[OCMEnvironment],
        init_ocm_base_client: Callable[
            [OCMAPIClientConfigurationProtocol, SecretReaderBase], OCMBaseClient
        ] = init_ocm_base_client,
    ) -> dict[str, OCMBaseClient]:
        return {
            env.name: init_ocm_base_client(env, self.secret_reader)
            for env in environments
        }

    def get_early_exit_desired_state(self) -> Optional[dict[str, Any]]:
        # gqlapi = gql.get_api()
        # return {"clusters": [c.dict() for c in self.get_clusters(gqlapi.query)]}
        return {}

    def run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()
        clusters = self.get_clusters(gqlapi.query)
        organizations = self.get_organizations(gqlapi.query)
        environments = self.get_environments(gqlapi.query)

        self.ocm_apis = self.init_ocm_apis(environments, init_ocm_base_client)

        # organization labels
        orgs_current_state, orgs_desired_state = self.fetch_organization_label_states(
            organizations
        )
        self.reconcile(
            dry_run=dry_run,
            scope="organization",
            current_state=orgs_current_state,
            desired_state=orgs_desired_state,
        )

        # subscription labels
        subs_current_state, subs_desired_state = self.fetch_subscription_label_states(
            clusters
        )
        self.reconcile(
            dry_run=dry_run,
            scope="cluster",
            current_state=subs_current_state,
            desired_state=subs_desired_state,
        )

    def fetch_organization_label_states(
        self, organizations: Iterable[OpenShiftClusterManagerV1]
    ) -> tuple[
        dict[LabelOwnerRef, dict[str, str]], dict[LabelOwnerRef, dict[str, str]]
    ]:
        """
        Returns the current and desired state of the organizations labels for
        the given organizations.

        Please note that the current state might not contain all requested organizations,
        e.g. if a organization can't be found in OCM.
        """
        label_sources: list[LabelSource] = [
            init_aus_org_label_source(gql.get_api().query),
        ]
        managed_label_prefixes = (
            managed_label_prefixes
        ) = self.manged_label_prefixes_from_sources(label_sources)

        current_state = self.fetch_organization_label_current_state(
            organizations, list(managed_label_prefixes)
        )
        desired_state = self.fetch_desired_state(label_sources)
        return current_state, desired_state

    def fetch_organization_label_current_state(
        self,
        organizations: Iterable[OpenShiftClusterManagerV1],
        managed_label_prefixes: list[str],
    ) -> dict[LabelOwnerRef, dict[str, str]]:
        """
        Fetches the current state of organizations labels for the given organizations.
        If an organization can't be found in OCM, the resulting dict will not contain a
        state for it, not even an empty one.

        Only labels with a prefix in managed_label_prefixes are returned. Not every label
        on an organizations is this integrations business.
        """
        states: dict[LabelOwnerRef, dict[str, str]] = {}

        # prepare search filters
        managed_label_filter = Filter()
        for prefix in managed_label_prefixes:
            managed_label_filter |= Filter().like("key", f"{prefix}%")

        for env_name, ocm_api in self.ocm_apis.items():
            env_orgs = {
                o.org_id: o for o in organizations if o.environment.name == env_name
            }
            if not env_orgs:
                continue
            labels_by_org_id = get_org_labels(
                ocm_api=ocm_api,
                org_ids=set(env_orgs.keys()),
                label_filter=managed_label_filter,
            )
            for org_id, labels in labels_by_org_id.items():
                states[
                    OrgRef(
                        org_id=org_id,
                        ocm_env=env_name,
                        label_container_href=build_organization_labels_href(org_id),
                        name=env_orgs[org_id].name,
                    )
                ] = labels.get_values_dict()

        return states

    def fetch_subscription_label_states(
        self, clusters: list[ClusterV1]
    ) -> tuple[
        dict[LabelOwnerRef, dict[str, str]], dict[LabelOwnerRef, dict[str, str]]
    ]:
        """
        Returns the current and desired state of the subscription labels for
        the given clusters.

        Please note that the current state might not contain all requested clusters,
        e.g. if a cluster can't be found in OCM or is not considered ready yet.
        """
        label_sources: list[LabelSource] = [
            init_cluster_subscription_label_source(
                clusters, self.params.managed_label_prefixes
            ),
            init_aus_cluster_label_source(gql.get_api().query),
        ]
        managed_label_prefixes = self.manged_label_prefixes_from_sources(label_sources)

        current_state = self.fetch_subscription_label_current_state(
            clusters, list(managed_label_prefixes)
        )
        desired_state = self.fetch_desired_state(label_sources)
        return current_state, desired_state

    def fetch_subscription_label_current_state(
        self, clusters: Iterable[ClusterV1], managed_label_prefixes: list[str]
    ) -> dict[LabelOwnerRef, dict[str, str]]:
        """
        Fetches the current state of subscription labels for the given clusters.
        If a cluster can't be found in OCM, the resulting dict will not contain a
        state for it, not even an empty one.

        Only labels with a prefix in managed_label_prefixes are returned. Not every label
        on a subscription is this integrations business.
        """
        cluster_ids = {c.spec.q_id for c in clusters if c.spec and c.spec.q_id}
        states: dict[LabelOwnerRef, dict[str, str]] = {}
        for env_name, ocm_api in self.ocm_apis.items():
            for cluster_details in discover_clusters_for_organizations(
                ocm_api=ocm_api,
                organization_ids=list(
                    {
                        c.ocm.org_id
                        for c in clusters
                        if c.ocm and c.ocm.environment.name == env_name
                    }
                ),
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

    def fetch_desired_state(
        self, sources: list[LabelSource]
    ) -> dict[LabelOwnerRef, dict[str, str]]:
        states: dict[LabelOwnerRef, dict[str, str]] = defaultdict(dict)
        for s in sources:
            for cluster_ref, labels in s.get_labels().items():
                states[cluster_ref].update(labels)

        return dict(states)

    def manged_label_prefixes_from_sources(
        self, label_sources: list[LabelSource]
    ) -> set[str]:
        prefixes = set()
        for source in label_sources:
            for s in source.managed_label_prefixes():
                if s in prefixes:
                    raise ManagedLabelPrefixConflictError(
                        f"Label prefix '{s}' from {type(s)} is already managed by another label source"
                    )
                for i in range(1, len(s)):
                    prefix = s[:i]
                    if prefix in prefixes:
                        raise ManagedLabelPrefixConflictError(
                            f"Label prefix '{s}' from {type(s)} is already managed by another label source"
                        )
                prefixes.add(s)
        return prefixes

    def reconcile(
        self,
        dry_run: bool,
        scope: str,
        current_state: dict[LabelOwnerRef, dict[str, str]],
        desired_state: dict[LabelOwnerRef, dict[str, str]],
    ) -> None:
        # we iterate via the current state because it refers to the clusters we can act on
        for label_owner_ref, current_labels in current_state.items():
            ocm_api = self.ocm_apis[label_owner_ref.ocm_env]
            desired_labels = desired_state.get(label_owner_ref, {})
            if current_labels == desired_labels:
                continue

            diff_result = diff_mappings(current_labels, desired_labels)

            for label_to_add, value in diff_result.add.items():
                logging.info(
                    [
                        f"create_{scope}_label",
                        *label_owner_ref.identity_labels(),
                        f"{label_to_add}={value}",
                    ]
                )
                if not dry_run:
                    add_label(
                        ocm_api=ocm_api,
                        label_container_href=label_owner_ref.required_label_container_href(),
                        label=label_to_add,
                        value=value,
                    )
            for label_to_rm, value in diff_result.delete.items():
                logging.info(
                    [
                        f"delete_{scope}_label",
                        *label_owner_ref.identity_labels(),
                        f"{label_to_rm}={value}",
                    ]
                )
                if not dry_run:
                    delete_label(
                        ocm_api=ocm_api,
                        label_container_href=label_owner_ref.required_label_container_href(),
                        label=label_to_rm,
                    )
            for label_to_update, diff_pair in diff_result.change.items():
                value = diff_pair.desired
                logging.info(
                    [
                        f"update_{scope}_label",
                        *label_owner_ref.identity_labels(),
                        f"{label_to_update}={value}",
                    ]
                )
                if not dry_run:
                    update_label(
                        ocm_api=ocm_api,
                        label_container_href=label_owner_ref.required_label_container_href(),
                        label=label_to_update,
                        value=value,
                    )


def init_cluster_subscription_label_source(
    clusters: list[ClusterV1], parent_prefixes: Iterable[str]
) -> ClusterSubscriptionLabelSource:
    # find the managed prefixes based on current label data in clusters
    def next_segment(prefix: str, label: str) -> Optional[str]:
        if label.startswith(prefix):
            return label[len(prefix) + 1 :].split(".")[0]
        return None

    managed_prefixes = set()
    for parent_prefix in parent_prefixes:
        for cluster in clusters:
            for label in flatten(cluster.ocm_subscription_labels or {}):
                segment = next_segment(parent_prefix, label)
                if segment:
                    managed_prefixes.add(f"{parent_prefix}.{segment}")

    return ClusterSubscriptionLabelSource(
        clusters=[
            c
            for c in clusters or []
            if c.ocm is not None and integration_is_enabled(QONTRACT_INTEGRATION, c)
        ],
        managed_prefixes=managed_prefixes,
    )


class ClusterSubscriptionLabelSource(LabelSource):
    def __init__(
        self, clusters: Iterable[ClusterV1], managed_prefixes: set[str]
    ) -> None:
        self.clusters = clusters
        self.managed_prefixes = managed_prefixes

    def managed_label_prefixes(self) -> set[str]:
        return self.managed_prefixes

    def get_labels(self) -> dict[LabelOwnerRef, dict[str, str]]:
        return {
            ClusterRef(
                cluster_id=cluster.spec.q_id,
                org_id=cluster.ocm.org_id,
                ocm_env=cluster.ocm.environment.name,
                name=cluster.name,
                label_container_href=None,
            ): flatten(cluster.ocm_subscription_labels or {})
            for cluster in self.clusters
            if cluster.ocm and cluster.spec and cluster.spec.q_id
        }
