import base64
import logging
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.metrics import (
    DTPClustersManagedGauge,
    DTPOrganizationErrorRate,
)
from reconcile.dynatrace_token_provider.model import DynatraceAPIToken, K8sSecret
from reconcile.dynatrace_token_provider.ocm import Cluster, OCMClient
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceAPITokenV1,
    DynatraceTokenProviderTokenSpecV1,
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
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "dynatrace-token-provider"
SYNCSET_ID = "ext-dynatrace-tokens-dtp"
SECRET_NAME = "dynatrace-token-dtp"
SECRET_NAMESPACE = "dynatrace"


class DynatraceTokenProviderIntegrationParams(PydanticRunParams):
    ocm_organization_ids: set[str] | None = None


class ReconcileErrorSummary(Exception):
    def __init__(self, exceptions: Iterable[str]) -> None:
        self.exceptions = exceptions

    def __str__(self) -> str:
        formatted_exceptions = "\n".join([f"- {e}" for e in self.exceptions])
        return f"Reconcile exceptions:\n{formatted_exceptions}"


class DynatraceTokenProviderIntegration(
    QontractReconcileIntegration[DynatraceTokenProviderIntegrationParams]
):
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
        dependencies.populate()
        self.reconcile(dry_run=dry_run, dependencies=dependencies)

    def reconcile(self, dry_run: bool, dependencies: Dependencies) -> None:
        with metrics.transactional_metrics(self.name):
            unhandled_exceptions = []
            for ocm_env_name, ocm_client in dependencies.ocm_client_by_env_name.items():
                clusters: list[Cluster] = []
                try:
                    clusters = ocm_client.discover_clusters_by_labels(
                        label_filter=subscription_label_filter().like(
                            "key", dtp_label_key("%")
                        ),
                    )
                except Exception as e:
                    unhandled_exceptions.append(f"{ocm_env_name}: {e}")
                metrics.set_gauge(
                    DTPClustersManagedGauge(
                        integration=self.name,
                        ocm_env=ocm_env_name,
                    ),
                    len(clusters),
                )
                if not clusters:
                    continue
                if self.params.ocm_organization_ids:
                    clusters = [
                        cluster
                        for cluster in clusters
                        if cluster.organization_id in self.params.ocm_organization_ids
                    ]
                dtp_tenant_label_key = f"{dtp_label_key(None)}.tenant"
                existing_dtp_tokens = {}

                for cluster in clusters:
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
                                    error=f"Missing label {dtp_tenant_label_key}",
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
                                continue
                            if tenant_id not in existing_dtp_tokens:
                                existing_dtp_tokens[tenant_id] = (
                                    dt_client.get_token_ids_for_name_prefix(
                                        prefix="dtp-"
                                    )
                                )

                            self.process_cluster(
                                dry_run=dry_run,
                                cluster=cluster,
                                dt_client=dt_client,
                                ocm_client=ocm_client,
                                existing_dtp_tokens=existing_dtp_tokens[tenant_id],
                                tenant_id=tenant_id,
                                token_spec=token_spec,
                            )
                    except Exception as e:
                        unhandled_exceptions.append(
                            f"{ocm_env_name}/{cluster.organization_id}/{cluster.external_id}: {e}"
                        )

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)

    def process_cluster(
        self,
        dry_run: bool,
        cluster: Cluster,
        dt_client: DynatraceClient,
        ocm_client: OCMClient,
        existing_dtp_tokens: Iterable[str],
        tenant_id: str,
        token_spec: DynatraceTokenProviderTokenSpecV1,
    ) -> None:
        if cluster.organization_id not in token_spec.ocm_org_ids:
            logging.info(
                f"[{token_spec.name=}] Cluster {cluster.external_id} is not part of ocm orgs defined in {token_spec.ocm_org_ids=}"
            )
            return
        existing_syncset = self.get_syncset(ocm_client, cluster)
        dt_api_url = f"https://{tenant_id}.live.dynatrace.com/api"
        if not existing_syncset:
            if not dry_run:
                try:
                    k8s_secrets = self.construct_secrets(
                        token_spec=token_spec,
                        dt_client=dt_client,
                        cluster_uuid=cluster.external_id,
                    )
                    if cluster.is_hcp:
                        # TODO:create manifest
                        pass
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
                        f"DTP can't create Syncset with the tokens {str(e.args)}",
                    )
            logging.info(
                f"Ingestion and operator tokens created in Dynatrace for {cluster.external_id=}."
            )
            logging.info(f"SyncSet {SYNCSET_ID} created for {cluster.external_id=}.")
        else:
            current_k8s_secrets: list[K8sSecret] = []
            if cluster.is_hcp:
                # TODO: get secrets from manifest
                pass
            else:
                current_k8s_secrets = self.get_secrets_from_syncset(
                    syncset=existing_syncset, token_spec=token_spec
                )
            has_diff, desired_secrets = self.generate_desired(
                dry_run=dry_run,
                current_k8s_secrets=current_k8s_secrets,
                desired_spec=token_spec,
                existing_dtp_tokens=existing_dtp_tokens,
                dt_client=dt_client,
                cluster_uuid=cluster.external_id,
            )
            if has_diff:
                if not dry_run:
                    try:
                        if cluster.is_hcp:
                            # TODO: patch manifest
                            pass
                        else:
                            ocm_client.patch_syncset(
                                cluster_id=cluster.id,
                                syncset_id=SYNCSET_ID,
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
                            f"DTP can't patch Syncset {SYNCSET_ID} due to {str(e.args)}",
                        )
                logging.info(
                    f"Syncset {SYNCSET_ID} patched for {cluster.external_id=}."
                )

    def generate_desired(
        self,
        dry_run: bool,
        current_k8s_secrets: Iterable[K8sSecret],
        desired_spec: DynatraceTokenProviderTokenSpecV1,
        existing_dtp_tokens: Iterable[str],
        dt_client: DynatraceClient,
        cluster_uuid: str,
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
                new_token = current_tokens_by_name.get(
                    desired_token.name,
                    DynatraceAPIToken(
                        token="",
                        id="does-for-sure-not-exist-3e14dab5801ed1f657425aca498ab008bac77f00deafd773695e394e434044d2",
                        name="",
                        secret_key="",
                    ),
                )
                if new_token.id not in existing_dtp_tokens:
                    has_diff = True
                    if not dry_run:
                        new_token = self.create_dynatrace_token(
                            dt_client, cluster_uuid, desired_token
                        )
                desired_tokens.append(new_token)
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
        token_name = f"{token.name}-{cluster_uuid}"
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
            syncset = ocm_client.get_syncset(cluster.id, SYNCSET_ID)
        except Exception as e:
            if "Not Found" in e.args[0]:
                syncset = None
            else:
                raise e
        return syncset

    def get_secrets_from_syncset(
        self, syncset: Mapping[str, Any], token_spec: DynatraceTokenProviderTokenSpecV1
    ) -> list[K8sSecret]:
        secrets: list[K8sSecret] = []
        secret_data_by_name = {
            resource.get("metadata", {}).get("name"): resource.get("data", {})
            for resource in syncset.get("resources", [])
            if resource.get("kind") == "Secret"
        }
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
            syncset["id"] = SYNCSET_ID
        return syncset


def dtp_label_key(config_atom: str | None) -> str:
    return sre_capability_label_key("dtp", config_atom)


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
