import logging
from typing import Optional

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.rhidp.common import (
    RHIDP_LABEL_KEY,
    RhidpLabelValue,
    build_cluster_auths,
    build_cluster_obj,
    discover_clusters,
)
from reconcile.rhidp.ocm_oidc_idp.base import run
from reconcile.utils import gql
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "ocm-oidc-idp-standalone"


class OCMOidcIdpStandaloneParams(PydanticRunParams):
    vault_input_path: str
    ocm_environment: Optional[str] = None
    ocm_organization_ids: Optional[set[str]] = None
    auth_name: str
    auth_issuer_url: str


class OCMOidcIdpStandalone(QontractReconcileIntegration[OCMOidcIdpStandaloneParams]):
    """A flavour of the OCM OIDC IDP integration, that uses
    OCM labels to discover clusters.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        for ocm_env in self.get_ocm_environments():
            ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
            # data query
            # clusters with enabled RHIDP
            clusters = self.get_clusters(
                ocm_api=ocm_api,
                ocm_env=ocm_env,
                label_value=RhidpLabelValue.ENABLED,
            )
            # with disabled RHIDP
            clusters += self.get_clusters(
                ocm_api=ocm_api,
                ocm_env=ocm_env,
                label_value=RhidpLabelValue.DISABLED,
            )
            if not clusters:
                logging.debug(f"No clusters with {RHIDP_LABEL_KEY} label found.")
                continue

            run(
                integration_name=self.name,
                ocm_environment=ocm_env.name,
                clusters=clusters,
                secret_reader=self.secret_reader,
                vault_input_path=f"{self.params.vault_input_path}/{ocm_env.name}",
                dry_run=dry_run,
                managed_idps=[self.params.auth_name],
            )

    def get_clusters(
        self,
        ocm_api: OCMBaseClient,
        ocm_env: OCMEnvironment,
        label_value: RhidpLabelValue,
    ) -> list[ClusterV1]:
        clusters_by_org = discover_clusters(
            ocm_api=ocm_api,
            org_ids=self.params.ocm_organization_ids,
            label_value=label_value,
        )

        return [
            build_cluster_obj(
                ocm_env=ocm_env,
                cluster=c,
                auth=build_cluster_auths(
                    name=self.params.auth_name,
                    issuer_url=self.params.auth_issuer_url,
                )
                if label_value == RhidpLabelValue.ENABLED
                else [],
            )
            for ocm_clusters in clusters_by_org.values()
            for c in ocm_clusters
        ]

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(
            gql.get_api().query,
            variables={"name": self.params.ocm_environment}
            if self.params.ocm_environment
            else None,
        ).environments
