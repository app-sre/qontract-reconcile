import base64
import hashlib
import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, MutableMapping
from datetime import timedelta
from threading import Lock
from typing import Any

from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.metrics import (
    DTPClustersManagedGauge,
    DTPOrganizationErrorRate,
    DTPTokensManagedGauge,
)
from reconcile.dynatrace_token_provider.model import DynatraceAPIToken, K8sSecret
from reconcile.dynatrace_token_provider.ocm import (
    DTP_LABEL_SEARCH,
    DTP_TENANT_LABEL,
    Cluster,
    OCMClient,
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
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "dynatrace-token-provider"
SYNCSET_AND_MANIFEST_ID = "ext-dynatrace-tokens-dtp"


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
            "specs": {
                spec.name: spec.dict()
                for spec in get_dynatrace_token_provider_token_specs()
            }
        }

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        dependencies = Dependencies(
            secret_reader=self.secret_reader,
            dynatrace_client_by_tenant_id={},
            ocm_client_by_env_name={},
            token_spec_by_name={},
        )
        dependencies.populate_all()
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

    def _filter_clusters(
        self,
        clusters: Iterable[Cluster],
        token_spec_by_name: Mapping[str, DynatraceTokenProviderTokenSpecV1],
    ) -> list[Cluster]:
        filtered_clusters = []
        for cluster in clusters:
            token_spec = token_spec_by_name.get(cluster.token_spec_name)
            if not token_spec:
                logging.debug(
                    f"[{cluster.external_id=}] Skipping cluster. {cluster.token_spec_name=} does not exist."
                )
                continue
            if cluster.organization_id in token_spec.ocm_org_ids:
                filtered_clusters.append(cluster)
            else:
                logging.debug(
                    f"[{cluster.external_id=}] Skipping cluster for {token_spec.name=}. {cluster.organization_id=} is not defined in {token_spec.ocm_org_ids=}."
                )
        return filtered_clusters

    def reconcile(self, dry_run: bool, dependencies: Dependencies) -> None:
        token_specs = list(dependencies.token_spec_by_name.values())
        validate_token_specs(specs=token_specs)

        with metrics.transactional_metrics(self.name):
            unhandled_exceptions = []
            for ocm_env_name, ocm_client in dependencies.ocm_client_by_env_name.items():
                clusters: list[Cluster] = []
                try:
                    clusters = ocm_client.discover_clusters_by_labels(
                        label_filter=subscription_label_filter().like(
                            "key", DTP_LABEL_SEARCH
                        ),
                    )
                except Exception as e:
                    unhandled_exceptions.append(f"{ocm_env_name}: {e}")
                if not clusters:
                    continue
                filtered_clusters = self._filter_clusters(
                    clusters=clusters,
                    token_spec_by_name=dependencies.token_spec_by_name,
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
                    try:
                        with DTPOrganizationErrorRate(
                            integration=self.name,
                            ocm_env=ocm_env_name,
                            org_id=cluster.organization_id,
                        ):
                            tenant_id = cluster.dt_tenant
                            if not tenant_id:
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster_uuid=cluster.external_id,
                                    error=f"Missing label {DTP_TENANT_LABEL}",
                                )
                                logging.warn(
                                    f"[{cluster.external_id=}] Missing value for label {DTP_TENANT_LABEL}"
                                )
                                continue
                            if (
                                tenant_id
                                not in dependencies.dynatrace_client_by_tenant_id
                            ):
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster_uuid=cluster.external_id,
                                    error=f"Dynatrace tenant {tenant_id} does not exist",
                                )
                                logging.warn(
                                    f"[{cluster.external_id=}] Dynatrace {tenant_id=} does not exist"
                                )
                                continue
                            dt_client = dependencies.dynatrace_client_by_tenant_id[
                                tenant_id
                            ]

                            token_spec = dependencies.token_spec_by_name.get(
                                cluster.token_spec_name
                            )
                            if not token_spec:
                                _expose_errors_as_service_log(
                                    ocm_client,
                                    cluster_uuid=cluster.external_id,
                                    error=f"Token spec {cluster.token_spec_name} does not exist",
                                )
                                logging.warn(
                                    f"[{cluster.external_id=}] Token spec '{cluster.token_spec_name}' does not exist"
                                )
                                continue
                            if tenant_id not in existing_dtp_tokens:
                                existing_dtp_tokens[tenant_id] = (
                                    dt_client.get_token_ids_map_for_name_prefix(
                                        prefix="dtp"
                                    )
                                )

                            """
                            Note, that we consciously do not parallelize cluster processing
                            for now. We want to keep stress on OCM at a minimum. The amount
                            of tagged clusters is currently feasible to be processed sequentially.
                            """
                            self.process_cluster(
                                dry_run=dry_run,
                                cluster=cluster,
                                dt_client=dt_client,
                                ocm_client=ocm_client,
                                existing_dtp_tokens=existing_dtp_tokens[tenant_id],
                                tenant_id=tenant_id,
                                token_spec=token_spec,
                                ocm_env_name=ocm_env_name,
                            )
                    except Exception as e:
                        unhandled_exceptions.append(
                            f"{ocm_env_name}/{cluster.organization_id}/{cluster.external_id}: {e}"
                        )
                self._expose_token_metrics()

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)

    def process_cluster(
        self,
        dry_run: bool,
        cluster: Cluster,
        dt_client: DynatraceClient,
        ocm_client: OCMClient,
        existing_dtp_tokens: MutableMapping[str, str],
        tenant_id: str,
        token_spec: DynatraceTokenProviderTokenSpecV1,
        ocm_env_name: str,
    ) -> None:
        existing_data = {}
        if cluster.is_hcp:
            existing_data = self.get_manifest(ocm_client=ocm_client, cluster=cluster)
        else:
            existing_data = self.get_syncset(ocm_client=ocm_client, cluster=cluster)
        dt_api_url = f"https://{tenant_id}.live.dynatrace.com/api"
        if not existing_data:
            if not dry_run:
                try:
                    k8s_secrets = self.construct_secrets(
                        token_spec=token_spec,
                        dt_client=dt_client,
                        cluster_uuid=cluster.external_id,
                    )
                    if cluster.is_hcp:
                        ocm_client.create_manifest(
                            cluster_id=cluster.id,
                            manifest_map=self.construct_manifest(
                                with_id=True,
                                dt_api_url=dt_api_url,
                                secrets=k8s_secrets,
                            ),
                        )
                    else:
                        ocm_client.create_syncset(
                            cluster_id=cluster.id,
                            syncset_map=self.construct_syncset(
                                with_id=True,
                                dt_api_url=dt_api_url,
                                secrets=k8s_secrets,
                            ),
                        )
                except Exception as e:
                    _expose_errors_as_service_log(
                        ocm_client,
                        cluster.external_id,
                        f"DTP can't create {token_spec.name=} {e.args!s}",
                    )
            logging.info(
                f"{token_spec.name=} created in {dt_api_url} for {cluster.external_id=}."
            )
            logging.info(
                f"{SYNCSET_AND_MANIFEST_ID} created for {cluster.external_id=}."
            )
        else:
            current_k8s_secrets: list[K8sSecret] = []
            if cluster.is_hcp:
                current_k8s_secrets = self.get_secrets_from_manifest(
                    manifest=existing_data, token_spec=token_spec
                )
            else:
                current_k8s_secrets = self.get_secrets_from_syncset(
                    syncset=existing_data, token_spec=token_spec
                )
            has_diff, desired_secrets = self.generate_desired(
                dry_run=dry_run,
                current_k8s_secrets=current_k8s_secrets,
                desired_spec=token_spec,
                existing_dtp_tokens=existing_dtp_tokens,
                dt_client=dt_client,
                cluster_uuid=cluster.external_id,
                dt_tenant_id=tenant_id,
                ocm_env_name=ocm_env_name,
            )
            if has_diff:
                if not dry_run:
                    try:
                        if cluster.is_hcp:
                            ocm_client.patch_manifest(
                                cluster_id=cluster.id,
                                manifest_id=SYNCSET_AND_MANIFEST_ID,
                                manifest_map=self.construct_manifest(
                                    dt_api_url=dt_api_url,
                                    secrets=desired_secrets,
                                    with_id=False,
                                ),
                            )
                        else:
                            ocm_client.patch_syncset(
                                cluster_id=cluster.id,
                                syncset_id=SYNCSET_AND_MANIFEST_ID,
                                syncset_map=self.construct_syncset(
                                    dt_api_url=dt_api_url,
                                    secrets=desired_secrets,
                                    with_id=False,
                                ),
                            )
                    except Exception as e:
                        _expose_errors_as_service_log(
                            ocm_client,
                            cluster.external_id,
                            f"DTP can't patch {token_spec.name=} for {SYNCSET_AND_MANIFEST_ID} due to {e.args!s}",
                        )
                logging.info(
                    f"Patched {token_spec.name=} for {SYNCSET_AND_MANIFEST_ID} in {cluster.external_id=}."
                )

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
        existing_dtp_tokens: MutableMapping[str, str],
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
                if cur_token:
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
                secrets.append(
                    K8sSecret(
                        secret_name=secret.name,
                        namespace_name=secret.namespace,
                        tokens=tokens,
                    )
                )
        return secrets

    def get_secrets_from_syncset(
        self, syncset: Mapping[str, Any], token_spec: DynatraceTokenProviderTokenSpecV1
    ) -> list[K8sSecret]:
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
        dt_api_url: str,
    ) -> list[dict[str, Any]]:
        secrets_data: list[dict[str, Any]] = []
        for secret in secrets:
            data: dict[str, str] = {
                "apiUrl": f"{self.base64_encode_str(dt_api_url)}",
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
                },
                "data": data,
            })
        return secrets_data

    def construct_base_syncset(
        self,
        secrets: Iterable[K8sSecret],
        dt_api_url: str,
    ) -> dict[str, Any]:
        return {
            "kind": "SyncSet",
            "resources": self.construct_secrets_data(
                secrets=secrets, dt_api_url=dt_api_url
            ),
        }

    def construct_base_manifest(
        self,
        secrets: Iterable[K8sSecret],
        dt_api_url: str,
    ) -> dict[str, Any]:
        return {
            "kind": "Manifest",
            "workloads": self.construct_secrets_data(
                secrets=secrets, dt_api_url=dt_api_url
            ),
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
        dt_api_url: str,
        with_id: bool,
    ) -> dict[str, Any]:
        syncset = self.construct_base_syncset(
            secrets=secrets,
            dt_api_url=dt_api_url,
        )
        if with_id:
            syncset["id"] = SYNCSET_AND_MANIFEST_ID
        return syncset

    def construct_manifest(
        self,
        secrets: Iterable[K8sSecret],
        dt_api_url: str,
        with_id: bool,
    ) -> dict[str, Any]:
        manifest = self.construct_base_manifest(
            secrets=secrets,
            dt_api_url=dt_api_url,
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
