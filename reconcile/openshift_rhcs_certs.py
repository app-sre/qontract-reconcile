import logging
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb
from reconcile.gql_definitions.common.rhcs_provider_settings import (
    RhcsProviderSettingsV1,
)
from reconcile.gql_definitions.rhcs.certs import (
    NamespaceOpenshiftResourceRhcsCertV1,
    NamespaceV1,
)
from reconcile.gql_definitions.rhcs.certs import (
    query as rhcs_certs_query,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.rhcs_provider_settings import get_rhcs_provider_settings
from reconcile.utils import gql, metrics
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.metrics import GaugeMetric, normalize_integration_name
from reconcile.utils.oc_map import init_oc_map_from_namespaces
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    ResourceInventory,
    base64_encode_secret_field_value,
)
from reconcile.utils.rhcsv2_certs import RhcsV2Cert, generate_cert
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import SecretNotFoundError, VaultClient

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
    renewal_threshold_days: str

    @classmethod
    def name(cls) -> str:
        return "qontract_reconcile_rhcs_cert_expiration_timestamp"


def _is_rhcs_cert(obj: Any) -> bool:
    return getattr(obj, "provider", None) == "rhcs-cert"


def get_namespaces_with_rhcs_certs(
    query_func: Callable,
    cluster_name: Iterable[str] | None = None,
) -> list[NamespaceV1]:
    result: list[NamespaceV1] = []
    for ns in rhcs_certs_query(query_func=query_func).namespaces or []:
        ob.aggregate_shared_resources_typed(cast("Any", ns))  # mypy: ignore[arg-type]
        if (
            integration_is_enabled(QONTRACT_INTEGRATION, ns.cluster)
            and not bool(ns.delete)
            and (not cluster_name or ns.cluster.name in cluster_name)
            and any(_is_rhcs_cert(r) for r in ns.openshift_resources or [])
        ):
            result.append(ns)
    return result


def construct_rhcs_cert_oc_secret(
    secret_name: str, cert: Mapping[str, Any], annotations: Mapping[str, str]
) -> OR:
    body: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "kubernetes.io/tls",
        "metadata": {"name": secret_name, "annotations": annotations},
    }
    for k, v in cert.items():
        v = base64_encode_secret_field_value(v)
        body.setdefault("data", {})[k] = v
    return OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)


def cert_expires_within_threshold(
    ns: NamespaceV1,
    cert_resource: NamespaceOpenshiftResourceRhcsCertV1,
    vault_cert_secret: Mapping[str, Any],
) -> bool:
    auto_renew_threshold_days = cert_resource.auto_renew_threshold_days or 7
    expires_in = int(vault_cert_secret["expiration_timestamp"]) - time.time()
    threshold_in_seconds = 60 * 60 * 24 * auto_renew_threshold_days
    if expires_in < threshold_in_seconds:
        logging.info(
            f"Existing cert expires within threshold: cluster='{ns.cluster.name}', namespace='{ns.name}', secret='{cert_resource.secret_name}', threshold='{auto_renew_threshold_days} days'"
        )
        return True
    return False


def get_vault_cert_secret(
    ns: NamespaceV1,
    cert_resource: NamespaceOpenshiftResourceRhcsCertV1,
    vault: VaultClient,
    vault_base_path: str,
) -> dict | None:
    vault_cert_secret = None
    try:
        vault_cert_secret = vault.read_all({
            "path": f"{vault_base_path}/{ns.cluster.name}/{ns.name}/{cert_resource.secret_name}"
        })
    except SecretNotFoundError:
        logging.info(
            f"No existing cert found for cluster='{ns.cluster.name}', namespace='{ns.name}', secret='{cert_resource.secret_name}''"
        )
    return vault_cert_secret


def generate_vault_cert_secret(
    dry_run: bool,
    ns: NamespaceV1,
    cert_resource: NamespaceOpenshiftResourceRhcsCertV1,
    vault: VaultClient,
    vault_base_path: str,
    issuer_url: str,
    ca_cert_url: str,
) -> dict:
    logging.info(
        f"Creating cert with service account credentials for '{cert_resource.service_account_name}'. cluster='{ns.cluster.name}', namespace='{ns.name}', secret='{cert_resource.secret_name}'"
    )
    sa_password = vault.read(cert_resource.service_account_password.dict())
    if dry_run:
        rhcs_cert = RhcsV2Cert(
            certificate="PLACEHOLDER_CERT",
            private_key="PLACEHOLDER_PRIVATE_KEY",
            ca_cert="PLACEHOLDER_CA_CERT",
            expiration_timestamp=int(time.time()),
        )
    else:
        try:
            rhcs_cert = generate_cert(
                issuer_url, cert_resource.service_account_name, sa_password, ca_cert_url
            )
        except ValueError as e:
            raise Exception(
                f"Certificate generation failed using service account '{cert_resource.service_account_name}': {e}"
            ) from None
        logging.info(
            f"Writing cert details to Vault at {vault_base_path}/{ns.cluster.name}/{ns.name}/{cert_resource.secret_name}"
        )
        vault.write(
            secret={
                "data": rhcs_cert.dict(by_alias=True),
                "path": f"{vault_base_path}/{ns.cluster.name}/{ns.name}/{cert_resource.secret_name}",
            },
            decode_base64=False,
        )
    return rhcs_cert.dict(by_alias=True)


def fetch_openshift_resource_for_cert_resource(
    dry_run: bool,
    ns: NamespaceV1,
    cert_resource: NamespaceOpenshiftResourceRhcsCertV1,
    vault: VaultClient,
    rhcs_settings: RhcsProviderSettingsV1,
) -> OR:
    vault_base_path = f"{rhcs_settings.vault_base_path}/{QONTRACT_INTEGRATION}"
    vault_cert_secret = get_vault_cert_secret(ns, cert_resource, vault, vault_base_path)
    if vault_cert_secret is None or cert_expires_within_threshold(
        ns, cert_resource, vault_cert_secret
    ):
        vault_cert_secret = generate_vault_cert_secret(
            dry_run,
            ns,
            cert_resource,
            vault,
            vault_base_path,
            rhcs_settings.issuer_url,
            rhcs_settings.ca_cert_url,
        )

    if not dry_run:
        metrics.set_gauge(
            OpenshiftRhcsCertExpiration(
                cert_name=cert_resource.secret_name,
                namespace=ns.name,
                cluster=ns.cluster.name,
                renewal_threshold_days=str(
                    cert_resource.auto_renew_threshold_days or 7
                ),
            ),
            int(vault_cert_secret["expiration_timestamp"]),
        )

    return construct_rhcs_cert_oc_secret(
        secret_name=cert_resource.secret_name,
        cert=vault_cert_secret,
        annotations=cert_resource.annotations or {},
    )


def fetch_desired_state(
    dry_run: bool,
    namespaces: list[NamespaceV1],
    ri: ResourceInventory,
    query_func: Callable,
) -> None:
    vault = VaultClient.get_instance()
    cert_provider = get_rhcs_provider_settings(query_func=query_func)
    for ns in namespaces:
        for cert_resource in ns.openshift_resources or []:
            if _is_rhcs_cert(cert_resource):
                ri.add_desired_resource(
                    cluster=ns.cluster.name,
                    namespace=ns.name,
                    resource=fetch_openshift_resource_for_cert_resource(
                        dry_run,
                        ns,
                        cast("NamespaceOpenshiftResourceRhcsCertV1", cert_resource),
                        vault,
                        cert_provider,
                    ),
                )


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    cluster_name: Iterable[str] | None = None,
    defer: Callable | None = None,
) -> None:
    gql_api = gql.get_api()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    namespaces = get_namespaces_with_rhcs_certs(gql_api.query, cluster_name)
    if not namespaces:
        logging.debug(
            f"No rhcs-cert definitions found in app-interface for {cluster_name}"
        )
        sys.exit(ExitCodes.SUCCESS)
    oc_map = init_oc_map_from_namespaces(
        namespaces=namespaces,
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    if defer:
        defer(oc_map.cleanup)
    ri = ResourceInventory()
    state_specs = ob.init_specs_to_fetch(
        ri,
        oc_map,
        namespaces=[ns.dict(by_alias=True) for ns in namespaces],
        override_managed_types=["Secret"],
    )
    for spec in state_specs:
        if isinstance(spec, ob.CurrentStateSpec):
            orb.fetch_current_state(
                spec.oc,
                ri,
                spec.cluster,
                spec.namespace,
                spec.kind,
                spec.resource_names,
            )
    fetch_desired_state(dry_run, namespaces, ri, gql_api.query)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    if ri.has_error_registered():
        sys.exit(1)
