import base64
import json
import logging
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from hashlib import shake_128
from typing import Any

from pydantic import BaseModel
from sretoolbox.utils import threaded

from reconcile.external_resources.meta import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
    SECRET_ANN_IDENTIFIER,
    SECRET_ANN_PROVIDER,
    SECRET_ANN_PROVISION_PROVIDER,
    SECRET_ANN_PROVISIONER,
    SECRET_UPDATED_AT,
    SECRET_UPDATED_AT_TIMEFORMAT,
)
from reconcile.external_resources.model import ExternalResourceKey
from reconcile.openshift_base import ApplyOptions, apply_action
from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.utils.differ import diff_mappings
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.oc import (
    OCCli,
)
from reconcile.utils.oc_map import OCMap, init_oc_map_from_clusters
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.secret_reader import SecretNotFound, SecretReaderBase
from reconcile.utils.three_way_diff_strategy import three_way_diff_using_hash
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,  # noqa
)


class VaultSecret(BaseModel):
    """Generic class to use the Protocol with Dicts"""

    path: str
    field: str
    version: int | None
    q_format: str | None


class SecretHelper:
    @staticmethod
    def get_comparable_secret(resource: OpenshiftResource) -> OpenshiftResource:
        metadata = {k: v for k, v in resource.body["metadata"].items()}
        metadata["annotations"] = {
            k: v
            for k, v in metadata.get("annotations", {}).items()
            if k != SECRET_UPDATED_AT
        }
        new = OpenshiftResource(
            body=resource.body | {"metadata": metadata},
            integration=resource.integration,
            integration_version=resource.integration_version,
            error_details=resource.error_details,
            caller_name=resource.caller_name,
            validate_k8s_object=False,
        )

        return new

    @staticmethod
    def is_newer(a: OpenshiftResource, b: OpenshiftResource) -> bool:
        try:
            # ISO8601 with the same TZ can be compared as strings.
            return a.annotations[SECRET_UPDATED_AT] > b.annotations[SECRET_UPDATED_AT]
        except (KeyError, ValueError) as e:
            logging.debug("Error comparing timestamps %s", e)
            return False

    @staticmethod
    def compare(current: OpenshiftResource, desired: OpenshiftResource) -> bool:
        if SECRET_UPDATED_AT not in current.annotations:
            logging.debug(
                "Current does not have the optimistic locking annotation. Apply"
            )
            return False
        # if current is newer; don't apply
        if SecretHelper.is_newer(current, desired):
            logging.debug("Current Secret is newer than Desired: Don't Apply")
            return True
        cmp_current = SecretHelper.get_comparable_secret(current)
        cmp_desired = SecretHelper.get_comparable_secret(desired)

        return three_way_diff_using_hash(cmp_current, cmp_desired)


class SecretsReconciler:
    def __init__(
        self,
        ri: ResourceInventory,
        secrets_reader: SecretReaderBase,
        thread_pool_size: int,
        dry_run: bool,
    ) -> None:
        self.secrets_reader = secrets_reader
        self.ri = ri
        self.thread_pool_size = thread_pool_size
        self.dry_run = dry_run

    @abstractmethod
    def _populate_secret_data(self, specs: Iterable[ExternalResourceSpec]) -> None:
        raise NotImplementedError()

    def _annotate(self, spec: ExternalResourceSpec) -> None:
        try:
            annotations = json.loads(spec.resource["annotations"])
        except Exception:
            annotations = {}
        annotations[SECRET_ANN_PROVISION_PROVIDER] = spec.provision_provider
        annotations[SECRET_ANN_PROVISIONER] = spec.provisioner_name
        annotations[SECRET_ANN_PROVIDER] = spec.provider
        annotations[SECRET_ANN_IDENTIFIER] = spec.identifier
        annotations[SECRET_UPDATED_AT] = spec.metadata[SECRET_UPDATED_AT]
        spec.resource["annotations"] = json.dumps(annotations)

    def _specs_with_secret(
        self,
        specs: Iterable[ExternalResourceSpec],
    ) -> Iterable[ExternalResourceSpec]:
        return [spec for spec in specs if spec.secret]

    def _add_secret_to_ri(
        self,
        spec: ExternalResourceSpec,
    ) -> None:
        self.ri.initialize_resource_type(
            spec.cluster_name, spec.namespace_name, "Secret"
        )
        self.ri.add_desired(
            spec.cluster_name,
            spec.namespace_name,
            "Secret",
            name=spec.output_resource_name,
            value=spec.build_oc_secret(
                QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            ).annotate(),
        )

    def _init_ocmap(self, specs: Iterable[ExternalResourceSpec]) -> OCMap:
        return init_oc_map_from_clusters(
            clusters=[
                c
                for c in get_clusters_minimal()
                if c.name in [o.cluster_name for o in specs]
            ],
            secret_reader=self.secrets_reader,
            integration=QONTRACT_INTEGRATION,
        )

    def sync_secrets(
        self, specs: Iterable[ExternalResourceSpec]
    ) -> list[ExternalResourceSpec]:
        """Sync outputs secrets to target clusters.
        Logic:
        Vault To Cluster:
            If current is newer; don't apply.
            If other changes; apply and Recycle Pods
            Desired can not be newer than current.
        External reosurce to Cluster (last reconciliation):
            If updated_at annotation is the only change; Don't update
            If other changes; Update Secret and Recycle Pods
            Current can not be newer then Desired

        :param specs: Specs that need sync the outputs secret to the target cluster
        :return: specs that produced errors when syncing secrets to clusters.
        """
        self._populate_secret_data(specs)

        to_sync_specs = [spec for spec in self._specs_with_secret(specs)]
        ocmap = self._init_ocmap(to_sync_specs)

        for spec in to_sync_specs:
            self._annotate(spec)
            self._add_secret_to_ri(spec)

        threaded.run(
            self.reconcile_data,
            self.ri,
            thread_pool_size=self.thread_pool_size,
            ocmap=ocmap,
        )

        if self.ri.has_error_registered():
            # Return all specs as error if there are errors.
            # There is no a clear way to kwno which specs failed.
            return list(specs)
        else:
            return []

    def reconcile_data(
        self,
        ri_item: tuple[str, str, str, Mapping[str, Any]],
        ocmap: OCMap,
    ) -> None:
        cluster, namespace, kind, data = ri_item
        oc = ocmap.get_cluster(cluster)
        names = list(data["desired"].keys())

        logging.debug(
            "Getting Secrets from cluster/namespace %s/%s", cluster, namespace
        )
        items = oc.get_items("Secret", namespace=namespace, resource_names=names)

        for item in items:
            current = OpenshiftResource(
                body=item,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )

            self.ri.add_current(
                cluster, namespace, kind, name=current.name, value=current
            )

        diff = diff_mappings(
            data["current"], data["desired"], equal=SecretHelper.compare
        )

        items_to_update = [item.desired for item in diff.change.values()] + list(
            diff.add.values()
        )

        self.apply_action(ocmap, cluster, namespace, items_to_update)

    def apply_action(
        self,
        ocmap: OCMap,
        cluster: str,
        namespace: str,
        items: Iterable[OpenshiftResource],
    ) -> None:
        options = ApplyOptions(
            dry_run=self.dry_run,
            no_dry_run_skip_compare=False,
            wait_for_namespace=False,
            recycle_pods=True,
            take_over=False,
            override_enable_deletion=False,
            caller=None,
            all_callers=None,
            privileged=None,
            enable_deletion=None,
        )
        for item in items:
            logging.debug(
                "Updating Secret Cluster: %s, Namespace: %s, Secret: %s",
                cluster,
                namespace,
                item.name,
            )

            apply_action(
                ocmap,
                self.ri,
                cluster,
                namespace,
                "Secret",
                item,
                options=options,
            )


class InClusterSecretsReconciler(SecretsReconciler):
    def __init__(
        self,
        ri: ResourceInventory,
        secrets_reader: SecretReaderBase,
        vault_path: str,
        vault_client: VaultClient,
        cluster: str,
        namespace: str,
        oc: OCCli,
        thread_pool_size: int,
        dry_run: bool,
    ):
        super().__init__(ri, secrets_reader, thread_pool_size, dry_run)

        self.cluster = cluster
        self.namespace = namespace
        self.oc = oc
        self.source_secrets: list[str] = []
        self.vault_client = vault_client
        self.vault_path = vault_path

    def _get_spec_hash(self, spec: ExternalResourceSpec) -> str:
        secret_key = f"{spec.provision_provider}-{spec.provisioner_name}-{spec.provider}-{spec.identifier}"
        return shake_128(secret_key.encode("utf-8")).hexdigest(16)

    def _get_spec_outputs_secret_name(self, spec: ExternalResourceSpec) -> str:
        return "external-resources-output-" + self._get_spec_hash(spec)

    def _populate_secret_data(self, specs: Iterable[ExternalResourceSpec]) -> None:
        if not specs:
            return

        secrets_map = {self._get_spec_outputs_secret_name(spec): spec for spec in specs}

        secrets = self.oc.get_items(
            "Secret", namespace=self.namespace, resource_names=list(secrets_map.keys())
        )

        for secret in secrets:
            secret_name = secret["metadata"]["name"]
            spec = secrets_map[secret_name]
            data = dict[str, str]()
            for k, v in secret["data"].items():
                decoded = base64.b64decode(v).decode("utf-8")

                if decoded.startswith("__vault__:"):
                    _secret_ref = json.loads(decoded.replace("__vault__:", ""))
                    secret_ref = VaultSecret(**_secret_ref)
                    data[k] = self.secrets_reader.read_secret(secret_ref)
                else:
                    data[k] = decoded

            spec.metadata[SECRET_UPDATED_AT] = datetime.now(UTC).strftime(
                SECRET_UPDATED_AT_TIMEFORMAT
            )
            spec.secret = data

    def _delete_source_secret(self, spec: ExternalResourceSpec) -> None:
        secret_name = self._get_spec_outputs_secret_name(spec)
        logging.debug("Deleting secret " + secret_name)
        self.oc.delete(namespace=self.namespace, kind="Secret", name=secret_name)

    def _write_secret_to_vault(self, spec: ExternalResourceSpec) -> None:
        secret_path = f"{self.vault_path}/{spec.cluster_name}/{spec.namespace_name}/{spec.identifier}"
        secret = {k: str(v) for k, v in spec.secret.items()}
        secret[SECRET_UPDATED_AT] = spec.metadata[SECRET_UPDATED_AT]
        desired_secret = {"path": secret_path, "data": secret}
        self.vault_client.write(desired_secret, decode_base64=False)  # type: ignore[attr-defined]

    def sync_secrets(
        self, specs: Iterable[ExternalResourceSpec]
    ) -> list[ExternalResourceSpec]:
        try:
            specs_with_error = super().sync_secrets(specs)
        except Exception as e:
            # There is no an easy way to map which secrets have not been reconciled with the specs. If the sync
            # fails at this stage all the involved specs will be retried in the next iteration
            logging.error(
                "Error syncing Secrets to clusters. "
                "All specs reconciled in this iteration are marked as pending secret synchronization\n%s",
                e,
            )
            return list(specs)

        for spec in self._specs_with_secret(specs):
            try:
                self._write_secret_to_vault(spec)
                self._delete_source_secret(spec)
            except Exception as e:
                key = ExternalResourceKey.from_spec(spec)
                logging.error(
                    "Error writing Secret to Vault or deleting the source secret: Key: %s, Secret: %s\n%s",
                    key,
                    self._get_spec_outputs_secret_name(spec),
                    e,
                )
                specs_with_error.append(spec)

        return specs_with_error


def build_incluster_secrets_reconciler(
    cluster: str,
    namespace: str,
    secrets_reader: SecretReaderBase,
    vault_path: str,
    thread_pool_size: int,
    dry_run: bool,
) -> InClusterSecretsReconciler:
    ri = ResourceInventory()
    ocmap = init_oc_map_from_clusters(
        clusters=[c for c in get_clusters_minimal() if c.name == cluster],
        secret_reader=secrets_reader,
        integration=QONTRACT_INTEGRATION,
    )
    oc = ocmap.get_cluster(cluster)
    return InClusterSecretsReconciler(
        cluster=cluster,
        namespace=namespace,
        ri=ri,
        oc=oc,
        vault_path=vault_path,
        vault_client=VaultClient(),
        secrets_reader=secrets_reader,
        thread_pool_size=thread_pool_size,
        dry_run=dry_run,
    )


class VaultSecretsReconciler(SecretsReconciler):
    def __init__(
        self,
        ri: ResourceInventory,
        secrets_reader: SecretReaderBase,
        vault_path: str,
        thread_pool_size: int,
        dry_run: bool,
    ):
        super().__init__(ri, secrets_reader, thread_pool_size, dry_run)
        self.secrets_reader = secrets_reader
        self.vault_path = vault_path

    def _populate_secret_data(self, specs: Iterable[ExternalResourceSpec]) -> None:
        threaded.run(self._read_secret, specs, self.thread_pool_size)

    def _read_secret(self, spec: ExternalResourceSpec) -> None:
        secret_path = f"{self.vault_path}/{spec.cluster_name}/{spec.namespace_name}/{spec.identifier}"
        try:
            logging.debug("Reading Secret %s", secret_path)
            data = self.secrets_reader.read_all({"path": secret_path})
            spec.metadata[SECRET_UPDATED_AT] = data[SECRET_UPDATED_AT]
            del data[SECRET_UPDATED_AT]
            spec.secret = data
        except SecretNotFound:
            logging.info("Error getting secret from vault, skipping. [%s]", secret_path)
