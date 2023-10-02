from collections.abc import Iterable
from typing import Callable

from reconcile.aus.advanced_upgrade_service import (
    aus_label_key,
    build_cluster_upgrade_policy_label_set,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_clusters import (
    ClusterUpgradePolicyV1,
    ClusterV1,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_clusters import (
    query as aus_clusters_query,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_organization import (
    query as aus_organizations_query,
)
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.ocm_labels.label_sources import (
    ClusterRef,
    LabelSource,
    LabelState,
    OrgRef,
)


class AUSClusterUpgradePolicyLabelSource(LabelSource):
    def __init__(self, clusters: Iterable[ClusterV1]) -> None:
        self.clusters = clusters

    def get_labels(self) -> LabelState:
        return {
            ClusterRef(
                cluster_id=cluster.spec.q_id,
                org_id=cluster.ocm.org_id,
                ocm_env=cluster.ocm.environment.name,
                name=cluster.name,
                label_container_href=None,
            ): self._cluster_to_labels(cluster.upgrade_policy)
            for cluster in self.clusters
            if cluster.ocm
            and cluster.spec
            and cluster.spec.q_id
            and cluster.upgrade_policy
        }

    def _cluster_to_labels(self, policy: ClusterUpgradePolicyV1) -> dict[str, str]:
        return build_cluster_upgrade_policy_label_set(
            workloads=policy.workloads,
            schedule=policy.schedule,
            soak_days=policy.conditions.soak_days or 0,
            mutexes=policy.conditions.mutexes,
            sector=policy.conditions.sector,
            blocked_versions=policy.conditions.blocked_versions,
        ).build_labels_dict()


def init_aus_cluster_label_source(
    query_fun: Callable,
) -> LabelSource:
    clusters = aus_clusters_query(query_func=query_fun).clusters or []
    return AUSClusterUpgradePolicyLabelSource(clusters=clusters)


class AUSOrganizationLabelSource(LabelSource):
    def __init__(self, organizations: Iterable[AUSOCMOrganization]) -> None:
        self.organizations = organizations

    def get_labels(self) -> LabelState:
        return {
            OrgRef(
                org_id=organization.org_id,
                ocm_env=organization.environment.name,
                label_container_href=None,
                name=organization.name,
            ): self._organization_to_labels(organization)
            for organization in self.organizations
        }

    def _organization_to_labels(
        self, organization: AUSOCMOrganization
    ) -> dict[str, str]:
        labels: dict[str, str] = {}
        # blocked versions
        if organization.blocked_versions:
            labels[aus_label_key("blocked-versions")] = ",".join(
                organization.blocked_versions
            )
        # sector dependencies
        for sector in organization.sectors or []:
            if sector.dependencies:
                labels[aus_label_key(f"sectors.{sector.name}")] = ",".join(
                    sorted([dep.name for dep in sector.dependencies])
                )
        # version-data sharing
        if organization.inherit_version_data:
            labels[aus_label_key("version-data.inherit")] = ",".join(
                sorted(
                    inherit.org_id
                    for inherit in organization.inherit_version_data or []
                )
            )
        if organization.publish_version_data:
            labels[aus_label_key("version-data.publish")] = ",".join(
                sorted(
                    publish.org_id
                    for publish in organization.publish_version_data or []
                )
            )
        return labels


def init_aus_org_label_source(query_fun: Callable) -> LabelSource:
    organizations = aus_organizations_query(query_func=query_fun).organizations or []
    return AUSOrganizationLabelSource(organizations=organizations)
