import logging
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.oum.base import OCMUserManagementIntegration
from reconcile.oum.labelset import build_cluster_config_from_labels
from reconcile.oum.models import (
    ClusterError,
    ClusterUserManagementConfiguration,
    ClusterUserManagementSpec,
    OrganizationUserManagementConfiguration,
)
from reconcile.utils.ocm.base import (
    OCMClusterServiceLogCreateModel,
    OCMServiceLogSeverity,
)
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import build_container_for_prefix
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.service_log import create_service_log
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)


class OCMStandaloneUserManagementIntegration(OCMUserManagementIntegration):
    @property
    def name(self) -> str:
        return "ocm-standalone-user-management"

    def get_user_mgmt_config_for_ocm_env(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUserManagementConfiguration]:
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        clusters_by_org = discover_clusters(
            ocm_api=ocm_api,
            org_ids=org_ids,
        )
        configs: dict[str, OrganizationUserManagementConfiguration] = {}
        for org_id, org_clusters in clusters_by_org.items():
            configs[org_id] = build_user_management_configurations(
                org_id=org_id,
                clusters=org_clusters,
                providers=self.group_member_provider_ids,
            )
        return configs

    def signal_cluster_reconcile_success(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        message: str,
    ) -> None:
        logging.info(message)
        if dry_run:
            return
        create_service_log(
            ocm_api=ocm_api,
            service_log=OCMClusterServiceLogCreateModel(
                cluster_uuid=spec.cluster.ocm_cluster.external_id,
                severity=OCMServiceLogSeverity.Info,
                summary="Reconciled cluster groups",
                description=message,
                service_name=self.name,
            ),
        )

    def signal_cluster_validation_error(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        error: Exception,
    ) -> None:
        """
        The standalone user management capability will not fail on a configuration
        validation issue. If issues should be noticed by an SRE team, alerts based on
        the `oum_organization_validation_errors` metric in the `reconcile.oum.metrics`
        module should be set up.
        """
        logging.warning(
            "Failed to reconcile cluster user group configuration in "
            f"OCM organization {spec.cluster.organization_id}",
            exc_info=error,
        )
        if dry_run:
            return
        create_service_log(
            ocm_api=ocm_api,
            service_log=OCMClusterServiceLogCreateModel(
                cluster_uuid=spec.cluster.ocm_cluster.external_id,
                severity=OCMServiceLogSeverity.Error,
                summary="Failed to reconcile cluster user group configuration",
                description=str(error),
                service_name=self.name,
            ),
            dedup_interval=timedelta(days=2),
        )

    def signal_cluster_reconcile_error(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        error: Exception,
    ) -> None:
        """
        The standalone user management capability will not fail on a cluster
        reconciliation issue. If issues should be noticed by an SRE team, alerts based on
        the `oum_organization_reconcile_errors` metric in the `reconcile.oum.metrics`
        module should be set up.

        The user is not notified via service logs because such reconcile issues are not
        actionable to them.
        """
        logging.warning(
            "Failed to reconcile cluster user group configuration on "
            f"cluster {spec.cluster.ocm_cluster.name} (id={spec.cluster.ocm_cluster.id}) "
            f"in the OCM organization {spec.cluster.organization_id}",
            exc_info=error,
        )


def user_mgmt_label_key(config_atom: str) -> str:
    """
    Generates label keys for the user management authz capability, compliant with the naming
    scheme defined in https://service.pages.redhat.com/dev-guidelines/docs/sre-capabilities/framework/ocm-labels/
    """
    return sre_capability_label_key("user-mgmt", config_atom)


def discover_clusters(
    ocm_api: OCMBaseClient,
    org_ids: Optional[set[str]] = None,
) -> dict[str, list[ClusterDetails]]:
    """
    Discover all clusters with user management enabled on their subscription
    or their organization. Return the discovered clusters grouped by OCM organization ID.

    If `org_ids` is provided, only clusters from the specified organizations will be returned.
    """
    clusters = discover_clusters_by_labels(
        ocm_api=ocm_api,
        label_filter=Filter().like("key", user_mgmt_label_key("%")),
    )

    # group by org ID
    # optionally also filter on org IDs
    clusters_by_org: dict[str, list[ClusterDetails]] = defaultdict(list)
    for c in clusters:
        passed_ocm_filters = org_ids is None or c.organization_id in org_ids
        if passed_ocm_filters:
            clusters_by_org[c.organization_id].append(c)

    return clusters_by_org


def build_user_management_configurations(
    org_id: str,
    clusters: list[ClusterDetails],
    providers: set[str],
) -> OrganizationUserManagementConfiguration:
    """
    Extracts the user management configuration from the cluster labels.
    """
    org_config = OrganizationUserManagementConfiguration(org_id=org_id)
    for c in clusters:
        cluster_config = ClusterUserManagementConfiguration(cluster=c)
        org_config.cluster_configs.append(cluster_config)
        for p in providers:
            provider_org_labels = build_container_for_prefix(
                c.organization_labels, user_mgmt_label_key(f"{p}."), True
            )
            provider_subs_labels = build_container_for_prefix(
                c.subscription_labels, user_mgmt_label_key(f"{p}."), True
            )
            if provider_org_labels or provider_subs_labels:
                try:
                    role_groups = build_cluster_config_from_labels(
                        provider=p,
                        org_labels=provider_org_labels,
                        subscription_labels=provider_subs_labels,
                    )
                    for role_id, group_refs in role_groups.items():
                        cluster_config.roles[role_id].extend(group_refs)

                except Exception as e:
                    cluster_config.errors.append(ClusterError(message=str(e)))
    return org_config
