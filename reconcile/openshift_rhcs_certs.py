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
    query as rhcs_cert_provider_query,
)
from reconcile.utils import gql
from reconcile.utils.rhcsv2_certs import generate_cert
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.semver_helper import make_semver
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


def reconcile_vault_rhcs_certs(
    dry_run: bool, vault_simulator: VaultClientSimulator | None
) -> None:
    gqlapi = gql.get_api()
    vault = VaultClient()
    cert_providers = rhcs_cert_provider_query(gqlapi.query)
    if not cert_providers.providers:
        raise Exception("No RHCS certificate providers defined")
    cp = cert_providers.providers[0]  # currently only anticipate one provider defined

    desired_rhcs_certs = fetch_desired_rhcs_certs(gqlapi)
    for cert in desired_rhcs_certs:
        vault_cert_secret = None
        need_cert = False

        # check if cert is tracked in Vault
        try:
            vault_cert_secret = vault.read_all({
                "path": f"{cp.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}"
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
                f"Generating cert using service account credentials for '{cert.sa_name}'. cluster='{cert.cluster}', namespace='{cert.namespace}', secret='{cert.name}'"
            )
            try:
                sa_password = vault.read(cert.sa_password.dict())
            except SecretNotFound:
                logging.error(
                    f"Unable to retrieve service account credentials at specified Vault path: {cert.sa_password.path}. Skipping"
                )
                continue
            if not dry_run:
                try:
                    rhcs_cert = generate_cert(cp.url, cert.sa_name, sa_password)
                except ValueError as e:
                    logging.error(
                        f"Failed to generate RHCS certificate {cert.name} using service account {cert.sa_name}: {e}"
                    )
                    continue
            logging.info(
                f"Writing cert details to Vault at {cp.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}"
            )
            if dry_run and vault_simulator:
                # necessary for evaluating the corresponding openshift Secret to create in next stage
                vault_simulator.write(
                    secret={
                        "data": {
                            "certificate": "DRY_RUN_CERTIFICATE",
                            "private_key": "DRY_RUN_PRIVATE_KEY",
                            "expiration_timestamp": int(time.time())
                            + 90 * 24 * 60 * 60,
                        },
                        "path": f"{cp.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}",
                    },
                    decode_base64=False,
                )
            else:
                vault.write(
                    secret={
                        "data": rhcs_cert.dict(),
                        "path": f"{cp.vault_base_path}/{cert.cluster}/{cert.namespace}/{cert.name}",
                    },
                    decode_base64=False,
                )


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
    if dry_run:
        vault_simulator = VaultClientSimulator()
        reconcile_vault_rhcs_certs(dry_run, vault_simulator)
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
        reconcile_vault_rhcs_certs(dry_run, None)
        orb.run(
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
            providers=PROVIDERS,
            cluster_name=cluster_name,
            namespace_name=namespace_name,
        )
