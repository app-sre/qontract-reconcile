from reconcile.rhidp.common import (
    build_cluster_objects,
    discover_clusters,
    get_ocm_environments,
    get_ocm_orgs_from_env,
)
from reconcile.rhidp.ocm_oidc_idp.base import run
from reconcile.utils.ocm_base_client import init_ocm_base_client
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "ocm-oidc-idp"


class OCMOidcIdpParams(PydanticRunParams):
    vault_input_path: str
    ocm_environment: str | None = None
    default_auth_name: str
    default_auth_issuer_url: str


class OCMOidcIdp(QontractReconcileIntegration[OCMOidcIdpParams]):
    """The OCM OIDC IDP integration manages the cluster OIDC OCM configuration and uses OCM labels to discover clusters."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        for ocm_env in get_ocm_environments(self.params.ocm_environment):
            ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
            # data query
            cluster_details = discover_clusters(
                ocm_api=ocm_api,
                org_ids={
                    org.org_id for org in get_ocm_orgs_from_env(ocm_env.name, self.name)
                },
            )
            clusters = build_cluster_objects(
                cluster_details=cluster_details,
                default_auth_name=self.params.default_auth_name,
                default_issuer_url=self.params.default_auth_issuer_url,
            )

            run(
                integration_name=self.name,
                ocm_environment=ocm_env.name,
                clusters=clusters,
                secret_reader=self.secret_reader,
                ocm_api=ocm_api,
                vault_input_path=f"{self.params.vault_input_path}/{ocm_env.name}",
                dry_run=dry_run,
                managed_idps=[self.params.default_auth_name],
            )
