import base64
import hashlib
import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import timedelta
from threading import Lock
from typing import Any

from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.metrics import (
    DTPClustersManagedGauge,
    DTPOrganizationErrorRate,
    DTPTokensManagedGauge,
)
from reconcile.dynatrace_token_provider.model import (
    Cluster,
    DynatraceAPIToken,
    K8sSecret,
    TokenSpecTenantBinding,
)
from reconcile.dynatrace_token_provider.ocm import (
    OCMClient,
    OCMCluster,
)
from reconcile.dynatrace_token_provider.validate import validate_token_specs
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceAPITokenV1,
    DynatraceTokenProviderTokenSpecV1,
)
from reconcile.typed_queries.dynatrace_token_provider_token_specs import (
    get_dynatrace_token_provider_token_specs,
)
from reconcile.utils import (
    metrics,
)
from reconcile.utils.dynatrace.client import DynatraceClient
from reconcile.utils.ocm.base import (
    OCMClusterServiceLogCreateModel,
    OCMServiceLogSeverity,
)
from reconcile.utils.ocm.labels import subscription_label_filter
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.openshift_resource import (
    QONTRACT_ANNOTATION_INTEGRATION,
    QONTRACT_ANNOTATION_INTEGRATION_VERSION,
)
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION_VERSION = make_semver(2, 0, 1)
QONTRACT_INTEGRATION = "dynatrace-token-provider"
SYNCSET_AND_MANIFEST_ID = "ext-dynatrace-tokens-dtp"
DTP_LABEL_SEARCH = sre_capability_label_key("dtp", "%")
DTP_TENANT_V2_LABEL = sre_capability_label_key("dtp.v2", "tenant")
DTP_SPEC_V2_LABEL = sre_capability_label_key("dtp.v2", "token-spec")
DTP_V3_PREFIX = sre_capability_label_key("dtp", "v3")
DTP_V3_SPEC_SUFFIX = "token-spec"
DTP_V3_TENANT_SUFFIX = "tenant"


class ReconcileErrorSummary(Exception):
    def __init__(self, exceptions: Iterable[str]) -> None:
        self.exceptions = exceptions

    def __str__(self) -> str:
        formatted_exceptions = "\n".join([f"- {e}" for e in self.exceptions])
        return f"Reconcile exceptions:\n{formatted_exceptions}"


class DynatraceTokenProviderIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())
        self._lock = Lock()
        self._managed_tokens_cnt: dict[str, Counter[str]] = defaultdict(Counter)

    def get_early_exit_desired_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return the desired state for early exit."""
        return {
            "version": QONTRACT_INTEGRATION_VERSION,
            "specs": {
                spec.name: spec.dict()
                for spec in get_dynatrace_token_provider_token_specs()
            },
        }

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        dependencies = Dependencies.create(
            secret_reader=self.secret_reader,
        )
        self.reconcile(dry_run=dry_run, dependencies=dependencies)

    def _token_cnt(self, dt_tenant_id: str, ocm_env_name: str) -> None:
        with self._lock:
            self._managed_tokens_cnt[ocm_env_name][dt_tenant_id] += 1

    def _expose_token_metrics(self) -> None:
        for ocm_env_name, counter_by_tenant_id in self._managed_tokens_cnt.items():
            for dt_tenant_id, cnt in counter_by_tenant_id.items():
                metrics.set_gauge(
                    DTPTokensManagedGauge(
                        integration=self.name,
                        ocm_env=ocm_env_name,
                        dt_tenant_id=dt_tenant_id,
                    ),
                    cnt,
                )

    def _parse_ocm_data_to_cluster(
        self, ocm_cluster: OCMCluster, dependencies: Dependencies
    ) -> Cluster | None:
        bindings: dict[str, TokenSpecTenantBinding] = {}
        for label in ocm_cluster.labels:
            if not label.startswith(DTP_V3_PREFIX):
                continue
            if not (
                label.endswith(DTP_V3_TENANT_SUFFIX)
                or label.endswith(DTP_V3_SPEC_SUFFIX)
            ):
                logging.warning(
                    f"[Bad DTPv3 label key] {label=} {ocm_cluster.id=} {ocm_cluster.subscription_id=}"
                )
                continue
            common_prefix = label.rsplit(".", 1)[0]
            if not (
                tenant := ocm_cluster.labels.get(
                    f"{common_prefix}.{DTP_V3_TENANT_SUFFIX}"
                )
            ):
                logging.warning(
                    f"[Missing {DTP_V3_TENANT_SUFFIX} for common label prefix {common_prefix=}] {ocm_cluster.id=} {ocm_cluster.subscription_id=}"
                )
                continue
            if not (
                spec_name := ocm_cluster.labels.get(
                    f"{common_prefix}.{DTP_V3_SPEC_SUFFIX}"
                )
            ):
                logging.warning(
                    f"[Missing {DTP_V3_SPEC_SUFFIX} for common label prefix {common_prefix=}] {ocm_cluster.id=} {ocm_cluster.subscription_id=}"
                )
                continue
            if not (spec := dependencies.token_spec_by_name.get(spec_name)):
                logging.warning(
                    f"[Missing spec '{spec_name}'] {ocm_cluster.id=} {ocm_cluster.subscription_id=}"
                )
                continue
            bindings[common_prefix] = TokenSpecTenantBinding(
                spec=spec,
                tenant_id=tenant,
            )

        if not bindings:
            # Stay backwards compatible with v2 for now
            dt_tenant = ocm_cluster.labels.get(DTP_TENANT_V2_LABEL)
            token_spec_name = ocm_cluster.labels.get(DTP_SPEC_V2_LABEL)
            token_spec = dependencies.token_spec_by_name.get(token_spec_name or "")
            if not dt_tenant or not token_spec:
                logging.warning(
                    f"[Missing DTP labels] {ocm_cluster.id=} {ocm_cluster.subscription_id=} {dt_tenant=} {token_spec_name=}"
                )
                return None
            bindings["v2"] = TokenSpecTenantBinding(
                spec=token_spec,
                tenant_id=dt_tenant,
            )

        bindings_list = list(bindings.values())

        for binding in bindings_list:
            if binding.tenant_id not in dependencies.dynatrace_client_by_tenant_id:
                logging.warning(
                    f"[{ocm_cluster.id=}] Dynatrace {binding.tenant_id=} does not exist"
                )
                return None

        return Cluster(
            id=ocm_cluster.id,
            external_id=ocm_cluster.external_id,
            organization_id=ocm_cluster.organization_id,
            is_hcp=ocm_cluster.is_hcp,
            dt_token_bindings=bindings_list,
        )

    def _filter_clusters(
        self,
        clusters: Iterable[Cluster],
    ) -> list[Cluster]:
        filtered_clusters = []
        for cluster in clusters:
            # Check if any token binding is valid for this cluster
            has_valid_binding = False
            for token_binding in cluster.dt_token_bindings:
                token_spec = token_binding.spec
                if cluster.organization_id in token_spec.ocm_org_ids:
                    has_valid_binding = True
                    break
                else:
                    logging.debug(
                        f"[{cluster.id=}] Skipping token binding for {token_spec.name=}. {cluster.organization_id=} is not defined in {token_spec.ocm_org_ids=}."
                    )

            if has_valid_binding:
                filtered_clusters.append(cluster)
            else:
                logging.debug(
                    f"[{cluster.id=}] Skipping cluster as it has no valid token bindings."
                )
        return filtered_clusters

    def reconcile(self, dry_run: bool, dependencies: Dependencies) -> None:
        token_specs = list(dependencies.token_spec_by_name.values())
        validate_token_specs(specs=token_specs)

        with metrics.transactional_metrics(self.name):
            unhandled_exceptions = []
            for ocm_env_name, ocm_client in dependencies.ocm_client_by_env_name.items():
                ocm_clusters: list[OCMCluster] = []
                try:
                    ocm_clusters = ocm_client.discover_clusters_by_labels(
                        label_filter=subscription_label_filter().like(
                            "key", DTP_LABEL_SEARCH
                        ),
                    )
                except Exception as e:
                    unhandled_exceptions.append(f"{ocm_env_name}: {e}")
                if not ocm_clusters:
                    continue
                clusters: list[Cluster] = [
                    cluster
                    for ocm_cluster in ocm_clusters
                    if (
                        cluster := self._parse_ocm_data_to_cluster(
                            ocm_cluster=ocm_cluster,
                            dependencies=dependencies,
                        )
                    )
                ]
                filtered_clusters = self._filter_clusters(
                    clusters=clusters,
                )

                existing_dtp_tokens: dict[str, dict[str, str]] = {}

                metrics.set_gauge(
                    DTPClustersManagedGauge(
                        integration=self.name,
                        ocm_env=ocm_env_name,
                    ),
                    len(clusters),
                )
                for cluster in filtered_clusters:
                    with DTPOrganizationErrorRate(
                        integration=self.name,
                        ocm_env=ocm_env_name,
                        org_id=cluster.organization_id,
                    ):
                        try:
                            self.process_cluster(
                                dry_run=dry_run,
                                cluster=cluster,
                                ocm_client=ocm_client,
                                existing_dtp_tokens=existing_dtp_tokens,
                                ocm_env_name=ocm_env_name,
                                dependencies=dependencies,
                            )

                        except Exception as e:
                            unhandled_exceptions.append(
                                f"{ocm_env_name}/{cluster.organization_id}/{cluster.id}: {e}"
                            )
                self._expose_token_metrics()

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)

    def process_cluster(
        self,
        dry_run: bool,
        cluster: Cluster,
        ocm_client: OCMClient,
        existing_dtp_tokens: dict[str, dict[str, str]],
        ocm_env_name: str,
        dependencies: Dependencies,
    ) -> None:
        current_secrets: list[K8sSecret] = []
        if cluster.is_hcp:
            data = self.get_manifest(ocm_client=ocm_client, cluster=cluster)
            for binding in cluster.dt_token_bindings:
                current_secrets.extend(
                    self.get_secrets_from_manifest(
                        manifest=data, token_spec=binding.spec
                    )
                )
        else:
            data = self.get_syncset(ocm_client=ocm_client, cluster=cluster)
            for binding in cluster.dt_token_bindings:
                current_secrets.extend(
                    self.get_secrets_from_syncset(syncset=data, token_spec=binding.spec)
                )

        desired_secrets: list[K8sSecret] = []
        has_diff = False
        for binding in cluster.dt_token_bindings:
            dt_client = dependencies.dynatrace_client_by_tenant_id[binding.tenant_id]
            if binding.tenant_id not in existing_dtp_tokens:
                existing_dtp_tokens[binding.tenant_id] = (
                    dt_client.get_token_ids_map_for_name_prefix(prefix="dtp")
                )
            cur_diff, cur_desired_secrets = self.generate_desired(
                dry_run=dry_run,
                current_k8s_secrets=current_secrets,
                desired_spec=binding.spec,
                existing_dtp_tokens=existing_dtp_tokens[binding.tenant_id],
                dt_client=dt_client,
                cluster_uuid=cluster.external_id,
                dt_tenant_id=binding.tenant_id,
                ocm_env_name=ocm_env_name,
            )
            desired_secrets.extend(cur_desired_secrets)
            has_diff |= cur_diff

        if not current_secrets:
            if not dry_run:
                try:
                    if cluster.is_hcp:
                        ocm_client.create_manifest(
                            cluster_id=cluster.id,
                            manifest_map=self.construct_manifest(
                                with_id=True,
                                secrets=desired_secrets,
                            ),
                        )
                    else:
                        ocm_client.create_syncset(
                            cluster_id=cluster.id,
                            syncset_map=self.construct_syncset(
                                with_id=True,
                                secrets=desired_secrets,
                            ),
                        )
                except Exception as e:
                    _expose_errors_as_service_log(
                        ocm_client,
                        cluster.external_id,
                        f"DTP can't create {SYNCSET_AND_MANIFEST_ID} due to {e.args!s}",
                    )
            logging.info(f"{SYNCSET_AND_MANIFEST_ID} created for {cluster.id=}.")
        elif has_diff:
            if not dry_run:
                try:
                    if cluster.is_hcp:
                        ocm_client.patch_manifest(
                            cluster_id=cluster.id,
                            manifest_id=SYNCSET_AND_MANIFEST_ID,
                            manifest_map=self.construct_manifest(
                                secrets=desired_secrets,
                                with_id=False,
                            ),
                        )
                    else:
                        ocm_client.patch_syncset(
                            cluster_id=cluster.id,
                            syncset_id=SYNCSET_AND_MANIFEST_ID,
                            syncset_map=self.construct_syncset(
                                secrets=desired_secrets,
                                with_id=False,
                            ),
                        )
                except Exception as e:
                    _expose_errors_as_service_log(
                        ocm_client,
                        cluster.external_id,
                        f"DTP can't patch {SYNCSET_AND_MANIFEST_ID} due to {e.args!s}",
                    )
            logging.info(f"Patched {SYNCSET_AND_MANIFEST_ID} in {cluster.id=}.")

    def dt_api_url(self, tenant_id: str) -> str:
        return f"https://{tenant_id}.live.dynatrace.com/api"

    def scopes_hash(self, scopes: Iterable[str], length: int) -> str:
        m = hashlib.sha256()
        msg = ",".join(sorted(scopes))
        m.update(msg.encode("utf-8"))
        return m.hexdigest()[:length]

    def dynatrace_token_name(self, spec: DynatraceAPITokenV1, cluster_uuid: str) -> str:
        scopes_hash = self.scopes_hash(scopes=spec.scopes, length=12)
        # We have a limit of 100 chars
        # cluster_uuid = 36 chars
        # scopes_hash = 12 chars
        # prefix + separators = 6 chars
        return f"dtp_{spec.name[:46]}_{cluster_uuid}_{scopes_hash}"

    def sync_token_in_dynatrace(
        self,
        token_id: str,
        spec: DynatraceAPITokenV1,
        cluster_uuid: str,
        dt_client: DynatraceClient,
        token_name_in_dt_api: str,
        ocm_env_name: str,
        dt_tenant_id: str,
        dry_run: bool,
    ) -> None:
        """
        We ensure that the given token is properly configured in Dynatrace
        according to the given spec.

        A list query on the tokens does not return each tokens configuration.
        We encode the token configuration in the token name to save API calls.
        """
        self._token_cnt(dt_tenant_id=dt_tenant_id, ocm_env_name=ocm_env_name)
        expected_name = self.dynatrace_token_name(spec=spec, cluster_uuid=cluster_uuid)
        if token_name_in_dt_api != expected_name:
            logging.info(
                f"{token_name_in_dt_api=} != {expected_name=}. Sync dynatrace token {token_id=} with {spec=} for {cluster_uuid=}."
            )
            if not dry_run:
                dt_client.update_token(
                    token_id=token_id, name=expected_name, scopes=spec.scopes
                )

    def generate_desired(
        self,
        dry_run: bool,
        current_k8s_secrets: Iterable[K8sSecret],
        desired_spec: DynatraceTokenProviderTokenSpecV1,
        existing_dtp_tokens: dict[str, str],
        dt_client: DynatraceClient,
        cluster_uuid: str,
        ocm_env_name: str,
        dt_tenant_id: str,
    ) -> tuple[bool, Iterable[K8sSecret]]:
        has_diff = False
        desired: list[K8sSecret] = []

        current_secrets_by_name = {
            secret.secret_name: secret for secret in current_k8s_secrets
        }

        for secret in desired_spec.secrets:
            desired_tokens: list[DynatraceAPIToken] = []
            current_secret = current_secrets_by_name.get(secret.name)
            current_tokens_by_name = (
                {token.name: token for token in current_secret.tokens}
                if current_secret
                else {}
            )
            for desired_token in secret.tokens:
                cur_token = current_tokens_by_name.get(desired_token.name)
                if not cur_token or cur_token.id not in existing_dtp_tokens:
                    has_diff = True
                    if not dry_run:
                        cur_token = self.create_dynatrace_token(
                            dt_client, cluster_uuid, desired_token
                        )
                        existing_dtp_tokens[cur_token.id] = cur_token.name
                if cur_token and cur_token.id in existing_dtp_tokens:
                    self.sync_token_in_dynatrace(
                        token_id=cur_token.id,
                        spec=desired_token,
                        cluster_uuid=cluster_uuid,
                        dt_client=dt_client,
                        dry_run=dry_run,
                        token_name_in_dt_api=existing_dtp_tokens[cur_token.id],
                        dt_tenant_id=dt_tenant_id,
                        ocm_env_name=ocm_env_name,
                    )
                    desired_tokens.append(cur_token)
            desired.append(
                K8sSecret(
                    secret_name=secret.name,
                    namespace_name=secret.namespace,
                    tokens=desired_tokens,
                    dt_api_url=self.dt_api_url(tenant_id=dt_tenant_id),
                )
            )

        return (has_diff, desired)

    def create_dynatrace_token(
        self, dt_client: DynatraceClient, cluster_uuid: str, token: DynatraceAPITokenV1
    ) -> DynatraceAPIToken:
        token_name = self.dynatrace_token_name(spec=token, cluster_uuid=cluster_uuid)
        new_token = dt_client.create_api_token(
            name=token_name,
            scopes=token.scopes,
        )
        secret_key = token.key_name_in_secret or token.name
        return DynatraceAPIToken(
            id=new_token.id,
            token=new_token.token,
            name=token_name,
            secret_key=secret_key,
        )

    def construct_secrets(
        self,
        token_spec: DynatraceTokenProviderTokenSpecV1,
        dt_client: DynatraceClient,
        dt_api_url: str,
        cluster_uuid: str,
    ) -> list[K8sSecret]:
        secrets: list[K8sSecret] = []
        for secret in token_spec.secrets:
            new_tokens: list[DynatraceAPIToken] = []
            for token in secret.tokens:
                new_token = self.create_dynatrace_token(dt_client, cluster_uuid, token)
                new_tokens.append(new_token)
            secrets.append(
                K8sSecret(
                    secret_name=secret.name,
                    namespace_name=secret.namespace,
                    tokens=new_tokens,
                    dt_api_url=dt_api_url,
                )
            )
        return secrets

    def get_syncset(self, ocm_client: OCMClient, cluster: Cluster) -> dict[str, Any]:
        try:
            syncset = ocm_client.get_syncset(cluster.id, SYNCSET_AND_MANIFEST_ID)
        except Exception as e:
            if "Not Found" in e.args[0]:
                syncset = None
            else:
                raise e
        return syncset

    def get_manifest(self, ocm_client: OCMClient, cluster: Cluster) -> dict[str, Any]:
        try:
            manifest = ocm_client.get_manifest(cluster.id, SYNCSET_AND_MANIFEST_ID)
        except Exception as e:
            if "Not Found" in e.args[0]:
                manifest = None
            else:
                raise e
        return manifest

    def get_secrets_from_data(
        self,
        secret_data_by_name: Mapping[str, Any],
        token_spec: DynatraceTokenProviderTokenSpecV1,
    ) -> list[K8sSecret]:
        secrets: list[K8sSecret] = []
        for secret in token_spec.secrets:
            secret_data = secret_data_by_name.get(secret.name)
            if secret_data:
                tokens = []
                for token in secret.tokens:
                    token_id = self.base64_decode(
                        secret_data.get(f"{token.key_name_in_secret}Id", "")
                    )
                    token_value = self.base64_decode(
                        secret_data.get(token.key_name_in_secret, "")
                    )
                    tokens.append(
                        DynatraceAPIToken(
                            id=token_id,
                            token=token_value,
                            name=token.name,
                            secret_key=token.key_name_in_secret,
                        )
                    )
                dt_api_url = self.base64_decode(secret_data.get("apiUrl", ""))
                secrets.append(
                    K8sSecret(
                        secret_name=secret.name,
                        namespace_name=secret.namespace,
                        tokens=tokens,
                        dt_api_url=dt_api_url,
                    )
                )
        return secrets

    def get_secrets_from_syncset(
        self, syncset: Mapping[str, Any], token_spec: DynatraceTokenProviderTokenSpecV1
    ) -> list[K8sSecret]:
        if not syncset:
            return []
        secret_data_by_name = {
            resource.get("metadata", {}).get("name"): resource.get("data", {})
            for resource in syncset.get("resources", [])
            if resource.get("kind") == "Secret"
        }
        return self.get_secrets_from_data(
            secret_data_by_name=secret_data_by_name, token_spec=token_spec
        )

    def get_secrets_from_manifest(
        self, manifest: Mapping[str, Any], token_spec: DynatraceTokenProviderTokenSpecV1
    ) -> list[K8sSecret]:
        if not manifest:
            return []
        secret_data_by_name = {
            resource.get("metadata", {}).get("name"): resource.get("data", {})
            for resource in manifest.get("workloads", [])
            if resource.get("kind") == "Secret"
        }
        return self.get_secrets_from_data(
            secret_data_by_name=secret_data_by_name, token_spec=token_spec
        )

    def construct_secrets_data(
        self,
        secrets: Iterable[K8sSecret],
    ) -> list[dict[str, Any]]:
        secrets_data: list[dict[str, Any]] = []
        for secret in secrets:
            data: dict[str, str] = {
                "apiUrl": f"{self.base64_encode_str(secret.dt_api_url)}",
            }
            for token in secret.tokens:
                data[token.secret_key] = f"{self.base64_encode_str(token.token)}"
                data[f"{token.secret_key}Id"] = f"{self.base64_encode_str(token.id)}"
            secrets_data.append({
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": secret.secret_name,
                    "namespace": secret.namespace_name,
                    "annotations": {
                        QONTRACT_ANNOTATION_INTEGRATION: QONTRACT_INTEGRATION,
                        QONTRACT_ANNOTATION_INTEGRATION_VERSION: QONTRACT_INTEGRATION_VERSION,
                    },
                },
                "data": data,
            })
        return secrets_data

    def construct_base_syncset(
        self,
        secrets: Iterable[K8sSecret],
    ) -> dict[str, Any]:
        return {
            "kind": "SyncSet",
            "resources": self.construct_secrets_data(secrets=secrets),
        }

    def construct_base_manifest(
        self,
        secrets: Iterable[K8sSecret],
    ) -> dict[str, Any]:
        return {
            "kind": "Manifest",
            "workloads": self.construct_secrets_data(secrets=secrets),
        }

    def base64_decode(self, encoded: str) -> str:
        data_bytes = base64.b64decode(encoded)
        return data_bytes.decode("utf-8")

    def base64_encode_str(self, string: str) -> str:
        data_bytes = string.encode("utf-8")
        encoded = base64.b64encode(data_bytes)
        return encoded.decode("utf-8")

    def construct_syncset(
        self,
        secrets: Iterable[K8sSecret],
        with_id: bool,
    ) -> dict[str, Any]:
        syncset = self.construct_base_syncset(
            secrets=secrets,
        )
        if with_id:
            syncset["id"] = SYNCSET_AND_MANIFEST_ID
        return syncset

    def construct_manifest(
        self,
        secrets: Iterable[K8sSecret],
        with_id: bool,
    ) -> dict[str, Any]:
        manifest = self.construct_base_manifest(
            secrets=secrets,
        )
        if with_id:
            manifest["id"] = SYNCSET_AND_MANIFEST_ID
        return manifest


def _expose_errors_as_service_log(
    ocm_api: OCMClient, cluster_uuid: str, error: str
) -> None:
    ocm_api.create_service_log(
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid=cluster_uuid,
            severity=OCMServiceLogSeverity.Warning,
            summary="Dynatrace Token Provider Errors",
            description=f"\n {error}",
            service_name=QONTRACT_INTEGRATION,
        ),
        dedup_interval=timedelta(days=1),
    )
