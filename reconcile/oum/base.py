import logging
from abc import (
    ABC,
    abstractmethod,
)
from collections import defaultdict
from typing import Optional

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationActionCounter as ReconcileActionCounter,
)
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationReconcileCounter as ReconcileCounter,
)
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationReconcileErrorCounter as ReconcileErrorCounter,
)
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationValidationErrorsGauge as ValidationErrorsGauge,
)
from reconcile.oum.models import (
    ClusterError,
    ClusterRoleReconcileResult,
    ClusterUserManagementSpec,
    OrganizationUserManagementConfiguration,
)
from reconcile.oum.providers import (
    GroupMemberProvider,
    init_ldap_group_member_provider,
)
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.ocm.base import (
    CAPABILITY_MANAGE_CLUSTER_ADMIN,
    OCMClusterGroupId,
)
from reconcile.utils.ocm.cluster_groups import (
    add_user_to_cluster_group,
    delete_user_from_cluster_group,
    get_cluster_groups,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)


class OCMUserManagementIntegrationParams(PydanticRunParams):
    ocm_environment: Optional[str] = None
    ocm_organization_ids: Optional[set[str]] = None
    group_provider_specs: list[str]


class OCMUserManagementIntegration(
    QontractReconcileIntegration[OCMUserManagementIntegrationParams], ABC
):
    def run(self, dry_run: bool) -> None:
        with metrics.transactional_metrics(self.name):
            # init group providers
            self.group_member_providers = get_group_providers(
                self.params.group_provider_specs
            )

            for ocm_env in self.get_ocm_environments():
                self.reconcile_ocm_environment(dry_run, ocm_env)

    @property
    def group_member_provider_ids(self) -> set[str]:
        return set(self.group_member_providers.keys())

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(
            gql.get_api().query,
            variables={"name": self.params.ocm_environment}
            if self.params.ocm_environment
            else None,
        ).environments

    @abstractmethod
    def get_user_mgmt_config_for_ocm_env(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUserManagementConfiguration]:
        """
        Discover cluster user mgmt configurations in the given OCM environment.
        If org_ids are provided, only return configurations for the given organizations.

        To be implemented by subclasses.
        """

    def reconcile_ocm_environment(self, dry_run: bool, ocm_env: OCMEnvironment) -> None:
        """
        Processes user management configuration for all OCM organizations
        within the given OCM environment.
        """
        org_configs = self.get_user_mgmt_config_for_ocm_env(
            ocm_env, self.params.ocm_organization_ids
        )

        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        for org_id, org_config in org_configs.items():
            specs = build_specs_from_config(org_config, self.group_member_providers)
            self.reconcile_ocm_organization(
                dry_run, ocm_api, org_id, ocm_env.name, specs
            )

    def reconcile_ocm_organization(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        org_id: str,
        ocm_env: str,
        cluster_specs: list[ClusterUserManagementSpec],
    ) -> None:
        """
        Process user management configuration for all clusters in the
        given OCM organization.
        """
        metrics.inc_counter(
            ReconcileCounter(
                integration=self.name,
                ocm_env=ocm_env,
                org_id=org_id,
            )
        )

        validation_errors = 0
        errors: list[Exception] = []
        for spec in cluster_specs:
            if spec.errors:
                validation_errors += 1
                validation_msg = "\n".join([m.message for m in spec.errors])
                self.signal_cluster_validation_error(
                    dry_run, ocm_api, spec, Exception(validation_msg)
                )
                continue
            reconcile_result = reconcile_cluster_roles(
                dry_run=dry_run,
                ocm_api=ocm_api,
                org_id=org_id,
                spec=spec,
            )

            # expose action metrics
            # we do this also in error situations to signal partial work
            # that has been done on a cluster
            metrics.inc_counter(
                ReconcileActionCounter(
                    integration=self.name,
                    ocm_env=ocm_env,
                    org_id=org_id,
                    action=ReconcileActionCounter.Action.AddUser,
                ),
                by=reconcile_result.users_added,
            )
            metrics.inc_counter(
                ReconcileActionCounter(
                    integration=self.name,
                    ocm_env=ocm_env,
                    org_id=org_id,
                    action=ReconcileActionCounter.Action.RemoveUser,
                ),
                by=reconcile_result.users_removed,
            )

            # signal errors
            if reconcile_result.error:
                self.signal_cluster_reconcile_error(
                    dry_run, ocm_api, spec, reconcile_result.error
                )
                errors.append(reconcile_result.error)

        # expose organization level metrics
        metrics.inc_counter(
            ReconcileErrorCounter(
                integration=self.name,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
            by=1 if len(errors) > 0 else 0,
        )
        metrics.set_gauge(
            ValidationErrorsGauge(
                integration=self.name,
                ocm_env=ocm_env,
                org_id=org_id,
            ),
            validation_errors,
        )

    @abstractmethod
    def signal_cluster_reconcile_success(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        message: str,
    ) -> None:
        """
        This method is called when the cluster reconcile operation was successful.
        """

    @abstractmethod
    def signal_cluster_validation_error(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        error: Exception,
    ) -> None:
        """
        This method is called when the configuration for a cluster is invalid.

        If this method throws an exception, reconciliation on the rest of the clusters
        of an organization will stop.
        """

    @abstractmethod
    def signal_cluster_reconcile_error(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        error: Exception,
    ) -> None:
        """
        This method is called when the cluster reconcile operation failed.

        If this method throws an exception, reconciliation on the rest of the clusters
        of an organization will stop.
        """


def reconcile_cluster_roles(
    dry_run: bool,
    ocm_api: OCMBaseClient,
    org_id: str,
    spec: ClusterUserManagementSpec,
) -> ClusterRoleReconcileResult:
    """
    Make sure that the cluster roles and given users are synced onto the cluster.
    This implies adding missing users and removing stale ones.
    Cluster roles not mentioned in the spec are not touched.
    """
    result = ClusterRoleReconcileResult()

    try:
        org_id = spec.cluster.organization_id
        cluster = spec.cluster.ocm_cluster
        desired_groups: dict[OCMClusterGroupId, set[str]] = spec.roles
        current_groups: dict[OCMClusterGroupId, set[str]] = {
            role_id: {u.id for u in group.users.items}
            for role_id, group in get_cluster_groups(
                ocm_api=ocm_api, cluster_id=cluster.id
            ).items()
            if group.users
        }
        # only process roles present in the desired state and ignore the ones that are not
        # this way a role can still be managed manually while another one is managed by this integration
        for group in desired_groups.keys():
            desired_members = desired_groups.get(group, set())
            current_members = current_groups.get(group, set())

            # add missing users
            for missing_user in desired_members - current_members:
                logging.info(
                    f"add user {missing_user} to {group.value} - cluster id={cluster.id}, name={cluster.name}, org={org_id}"
                )
                if not dry_run:
                    add_user_to_cluster_group(
                        ocm_api=ocm_api,
                        cluster_id=cluster.id,
                        user_name=missing_user,
                        group=group,
                    )
                result.users_added += 1
            # remove obsolete users
            for obsolete_user in current_members - desired_members:
                logging.info(
                    f"remove user {obsolete_user} from {group.value} -  cluster id={cluster.id}, name={cluster.name}, org={org_id}"
                )
                if not dry_run:
                    delete_user_from_cluster_group(
                        ocm_api=ocm_api,
                        cluster_id=cluster.id,
                        user_name=obsolete_user,
                        group=group,
                    )
                result.users_removed += 1
    except Exception as e:
        result.error = e

    return result


def build_specs_from_config(
    org_config: OrganizationUserManagementConfiguration,
    group_member_providers: dict[str, GroupMemberProvider],
) -> list[ClusterUserManagementSpec]:
    """
    Transforms the external provider/group references into actual user names.
    """
    # collect external group refs by provider so we can do a bulk resolve
    external_group_refs_by_provider: dict[str, set[str]] = defaultdict(set)
    for cluster_config in org_config.cluster_configs:
        for role_external_group_ref in cluster_config.roles.values():
            for external_group_ref in role_external_group_ref:
                external_group_refs_by_provider[external_group_ref.provider].add(
                    external_group_ref.group_id
                )

    # resolve all groups using the provider implementations
    external_group_members_by_provider: dict[str, dict[str, set[str]]] = {}
    for provider, group_ids in external_group_refs_by_provider.items():
        external_group_members_by_provider[provider] = group_member_providers[
            provider
        ].resolve_groups(group_ids)

    # build specs
    cluster_specs: list[ClusterUserManagementSpec] = []
    for cluster_config in org_config.cluster_configs:
        spec = ClusterUserManagementSpec(
            cluster=cluster_config.cluster,
            roles={},
            errors=cluster_config.errors,
        )
        cluster_specs.append(spec)

        # fill roles
        for (
            role_id,
            external_group_refs,
        ) in cluster_config.roles.items():
            spec.roles[role_id] = set()
            if (
                cluster_config.cluster.ocm_cluster.is_osd()
                and role_id == OCMClusterGroupId.CLUSTER_ADMINS
                and not cluster_config.cluster.is_capability_set(
                    CAPABILITY_MANAGE_CLUSTER_ADMIN, "true"
                )
            ):
                spec.errors.append(
                    ClusterError(
                        message="This cluster does not have the capability to manage the cluster-admins role. Go to https://red.ht/ohss-incident and request cluster-admin access."
                    )
                )
            for group_ref in external_group_refs:
                members = external_group_members_by_provider[group_ref.provider].get(
                    group_ref.group_id
                )
                if members is None:
                    spec.errors.append(
                        ClusterError(
                            message=f"{group_ref.provider} group {group_ref.group_id} for {role_id.value} not found"
                        )
                    )
                    continue
                spec.roles[role_id].update(members)

            if spec.errors:
                spec.roles = {}

    return cluster_specs


def get_group_providers(
    group_provider_specs: list[str],
) -> dict[str, GroupMemberProvider]:
    """
    Initialize the group member providers.
    """
    providers: dict[str, GroupMemberProvider] = {}
    for provider_spec in group_provider_specs:
        provider_name, provider_type, provider_args = provider_spec.split(":")
        if provider_type == "ldap":
            providers[provider_name] = init_ldap_group_member_provider(provider_args)
        else:
            raise ValueError(f"unknown group member provider type {provider_type}")
    return providers
