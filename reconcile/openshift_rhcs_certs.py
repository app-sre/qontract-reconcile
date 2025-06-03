import logging
import time
from collections.abc import Iterable

from pydantic import BaseModel

import reconcile.openshift_resources_base as orb
from reconcile.gql_definitions.rhcs.certs import (
    NamespaceOpenshiftResourceRhcsCertV1,
    VaultSecretV1_VaultSecretV1,
)
from reconcile.gql_definitions.rhcs.certs import (
    query as rhcs_certs_query,
)
from reconcile.gql_definitions.rhcs.providers import (
    RhcsCertProviderV1,
)
from reconcile.gql_definitions.rhcs.providers import (
    query as rhcs_cert_provider_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql, metrics
from reconcile.utils.metrics import GaugeMetric, normalize_integration_name
from reconcile.utils.rhcsv2_certs import generate_cert
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import (
    State,
    init_state,
)
from reconcile.utils.vault import SecretNotFound, VaultClient, VaultClientSimulator

QONTRACT_INTEGRATION = "openshift-rhcs-certs"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 9, 3)
PROVIDERS = ["rhcs-cert"]


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="cluster_name",
        shard_path_selectors={
            "state.*.shard",
        },
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )


class OpenshiftRhcsCertExpiration(GaugeMetric):
    """Expiration timestamp of RHCS certificate stored in Vault."""

    integration: str = normalize_integration_name(QONTRACT_INTEGRATION)
    cert_name: str
    cluster: str
    namespace: str

    @classmethod
    def name(cls) -> str:
        return "qontract_reconcile_rhcs_cert_expiration_timestamp"


class OpenshiftRhcsCert(BaseModel):
    name: str
    namespace: str
    cluster: str
    sa_name: str
    sa_password: VaultSecretV1_VaultSecretV1
    auto_renew_threshold_days: int


def fetch_desired_rhcs_certs(gqlapi: gql.GqlApi) -> list[OpenshiftRhcsCert]:
    certs: list[OpenshiftRhcsCert] = []
    for ns in rhcs_certs_query(gqlapi.query).namespaces or []:
        if not ns.openshift_resources:
            continue
        certs.extend(
            OpenshiftRhcsCert(
                name=r.secret_name,
                namespace=ns.name,
                cluster=ns.cluster.name,
                sa_name=r.service_account_name,
                sa_password=r.service_account_password,
                auto_renew_threshold_days=r.auto_renew_threshold_days or 7,
            )
            for r in ns.openshift_resources
            if isinstance(r, NamespaceOpenshiftResourceRhcsCertV1)
        )
    return certs


def create_or_update_certs(
    dry_run: bool,
    state: State,
    vault: VaultClient,
    desired_rhcs_certs: list[OpenshiftRhcsCert],
    cert_provider: RhcsCertProviderV1,
    vault_simulator: VaultClientSimulator | None,
) -> None:
    for cert in desired_rhcs_certs:
        vault_cert_secret = None
        need_cert = False

        try:
            vault_cert_secret = vault.read_all({  # type: ignore[attr-defined]
                "path": f"{cert_provider.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}"
            })
        except SecretNotFound:
            need_cert = True
            logging.info(
                f"No existing cert found for cluster='{cert.cluster}', namespace='{cert.namespace}', secret='{cert.name}', threshold='{cert.auto_renew_threshold_days} days'"
            )

        # validate cert expiration
        if vault_cert_secret:
            expires_in = int(vault_cert_secret["expiration_timestamp"]) - time.time()
            threshold_in_seconds = 60 * 60 * 24 * cert.auto_renew_threshold_days
            if expires_in < threshold_in_seconds:
                need_cert = True
                logging.info(
                    f"Existing cert expires within threshold: cluster='{cert.cluster}', namespace='{cert.namespace}', secret='{cert.name}', threshold='{cert.auto_renew_threshold_days} days'"
                )

        if need_cert:
            logging.info(
                f"Creating cert with service account credentials for '{cert.sa_name}'. cluster='{cert.cluster}', namespace='{cert.namespace}', secret='{cert.name}'"
            )
            try:
                sa_password = vault.read(cert.sa_password.dict())  # type: ignore[attr-defined]
            except SecretNotFound:
                logging.error(
                    f"Unable to retrieve service account credentials at specified Vault path: {cert.sa_password.path}. Skipping"
                )
                continue
            if not dry_run:
                try:
                    rhcs_cert = generate_cert(
                        cert_provider.url, cert.sa_name, sa_password
                    )
                except ValueError as e:
                    logging.error(
                        f"Failed to generate RHCS certificate {cert.name} using service account {cert.sa_name}: {e}"
                    )
                    continue
            logging.info(
                f"Writing cert details to Vault at {cert_provider.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}"
            )
            if dry_run and vault_simulator:
                # necessary for evaluating the corresponding openshift Secret to create in openshift_resources_base stage
                vault_simulator.write(
                    secret={
                        "data": {
                            "certificate": "DRY_RUN_CERTIFICATE",
                            "private_key": "DRY_RUN_PRIVATE_KEY",
                            "expiration_timestamp": int(time.time())
                            + 90 * 24 * 60 * 60,
                        },
                        "path": f"{cert_provider.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}",
                    },
                    decode_base64=False,
                )
            else:
                vault.write(  # type: ignore[attr-defined]
                    secret={
                        "data": rhcs_cert.dict(),
                        "path": f"{cert_provider.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}",
                    },
                    decode_base64=False,
                )
                state.add(
                    key=f"{cert.cluster}/{cert.namespace}/{cert.name}",
                    value={"expiration_timestamp": rhcs_cert.expiration_timestamp},
                )

        if not dry_run:
            metrics.set_gauge(
                OpenshiftRhcsCertExpiration(
                    cert_name=cert.name,
                    namespace=cert.namespace,
                    cluster=cert.cluster,
                ),
                rhcs_cert.expiration_timestamp
                if need_cert
                else int(vault_cert_secret["expiration_timestamp"]),
            )


def delete_certs(
    dry_run: bool,
    state: State,
    vault: VaultClient,
    desired_rhcs_certs: list[OpenshiftRhcsCert],
    cert_provider: RhcsCertProviderV1,
) -> None:
    desired_cert_map = {
        f"/{cert.cluster}/{cert.namespace}/{cert.name}": True
        for cert in desired_rhcs_certs
    }
    for outstanding_cert_key in state.ls():
        if outstanding_cert_key not in desired_cert_map:
            logging.info(
                f"Deleting certificate secret from Vault. path='{cert_provider.vault_base_path}/{outstanding_cert_key}'"
            )
            if not dry_run:
                vault.delete(f"{cert_provider.vault_base_path}{outstanding_cert_key}")  # type: ignore[attr-defined]
                state.rm(outstanding_cert_key)


def reconcile_vault_rhcs_certs(
    dry_run: bool, state: State, vault_simulator: VaultClientSimulator | None
) -> None:
    vault = VaultClient()
    gqlapi = gql.get_api()
    cert_providers = rhcs_cert_provider_query(gqlapi.query)
    if not cert_providers.providers:
        raise Exception("No RHCS certificate providers defined")
    cp = cert_providers.providers[0]  # currently only anticipate one provider defined

    desired_rhcs_certs = fetch_desired_rhcs_certs(gqlapi)
    create_or_update_certs(
        dry_run, state, vault, desired_rhcs_certs, cp, vault_simulator
    )
    delete_certs(dry_run, state, vault, desired_rhcs_certs, cp)


def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    cluster_name: Iterable[str] | None = None,
    namespace_name: str | None = None,
) -> None:
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    state = init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader)

    if dry_run:
        vault_simulator = VaultClientSimulator()
        reconcile_vault_rhcs_certs(dry_run, state, vault_simulator)
        with vault_simulator.patch_vault_client():
            orb.run(
                dry_run=dry_run,
                thread_pool_size=thread_pool_size,
                internal=internal,
                use_jump_host=use_jump_host,
                providers=PROVIDERS,
                cluster_name=cluster_name,
                namespace_name=namespace_name,
            )
    else:
        reconcile_vault_rhcs_certs(dry_run, state, None)
        orb.run(
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
            providers=PROVIDERS,
            cluster_name=cluster_name,
            namespace_name=namespace_name,
        )
