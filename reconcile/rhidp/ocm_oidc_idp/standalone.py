import logging
from typing import Optional

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.rhidp.common import (
    RHIDP_LABEL_KEY,
    build_cluster_obj,
    discover_clusters,
)
from reconcile.rhidp.ocm_oidc_idp.base import run
from reconcile.utils import gql
from reconcile.utils.ocm_base_client import init_ocm_base_client
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
            clusters = self.get_clusters(
                ocm_env=ocm_env, org_ids=self.params.ocm_organization_ids
            )
            # data query
            if not clusters:
                logging.debug(f"No clusters with {RHIDP_LABEL_KEY} label found.")
                continue

            run(
                integration_name=self.name,
                clusters=clusters,
                secret_reader=self.secret_reader,
                vault_input_path=self.params.vault_input_path,
                dry_run=dry_run,
            )

    def get_clusters(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> list[ClusterV1]:
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        clusters_by_org = discover_clusters(
            ocm_api=ocm_api,
            org_ids=org_ids,
        )

        return [
            build_cluster_obj(
                ocm_env=ocm_env,
                cluster=c,
                auth_name=self.params.auth_name,
                auth_issuer_url=self.params.auth_issuer_url,
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
