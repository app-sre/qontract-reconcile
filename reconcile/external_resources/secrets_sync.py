import base64
import json
import logging
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from hashlib import shake_128
from typing import Any, Optional

from pydantic import BaseModel
from sretoolbox.utils import threaded

from reconcile.external_resources.meta import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
)
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
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.three_way_diff_strategy import three_way_diff_using_hash
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,  # noqa
)


class VaultSecret(BaseModel):
    """Generic class to use the Protocol with Dicts"""

    path: str
    field: str
    version: Optional[int]
    q_format: Optional[str]


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
        annotations["external-resources/provision_provider"] = spec.provision_provider
        annotations["external-resources/provisioner_name"] = spec.provisioner_name
        annotations["external-resources/provider"] = spec.provider
        annotations["external-resources/identifier"] = spec.identifier
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

    def sync_secrets(self, specs: Iterable[ExternalResourceSpec]) -> None:
        self._populate_secret_data(specs)

        to_sync_specs = self._specs_with_secret(specs)
        for spec in to_sync_specs:
            self._annotate(spec)
            self._add_secret_to_ri(spec)

        ocmap = self._init_ocmap(to_sync_specs)
        threaded.run(
            self.reconcile_data,
            self.ri,
            thread_pool_size=self.thread_pool_size,
            ocmap=ocmap,
        )

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
            obj = OpenshiftResource(
                body=item,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            self.ri.add_current(cluster, namespace, kind, name=obj.name, value=obj)

        diff = diff_mappings(
            data["current"], data["desired"], equal=three_way_diff_using_hash
        )
        items_to_update = [i.desired for i in diff.change.values()] + list(
            diff.add.values()
        )
        self.apply_action(oc, namespace, items_to_update)

    def apply_action(
        self, oc: OCCli, namespace: str, items: Iterable[OpenshiftResource]
    ) -> None:
        for i in items:
            logging.debug(
                "Updating Secret Cluster: %s, Namespace: %s, Secret: %s",
                oc.cluster_name,
                namespace,
                i.name,
            )
            if not self.dry_run:
                oc.apply(namespace, resource=i)


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

            spec.secret = data

    def _delete_source_secrets(self, specs: Iterable[ExternalResourceSpec]) -> None:
        for spec in self._specs_with_secret(specs):
            secret_name = "external-resources-output-" + self._get_spec_hash(spec)
            logging.debug("Deleting secret " + secret_name)
            self.oc.delete(namespace=self.namespace, kind="Secret", name=secret_name)

    def _write_secrets_to_vault(self, specs: Iterable[ExternalResourceSpec]) -> None:
        for spec in self._specs_with_secret(specs):
            secret_path = f"{self.vault_path}/{spec.cluster_name}/{spec.namespace_name}/{spec.identifier}"
            stringified_secret = {k: str(v) for k, v in spec.secret.items()}
            desired_secret = {"path": secret_path, "data": stringified_secret}
            self.vault_client.write(desired_secret, decode_base64=False)  # type: ignore[attr-defined]

    def sync_secrets(self, specs: Iterable[ExternalResourceSpec]) -> None:
        super().sync_secrets(specs)
        self._write_secrets_to_vault(specs)
        self._delete_source_secrets(specs)


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
            spec.secret = data
        except Exception:
            msg = f"Error getting secret from vault, skipping. [{secret_path}]"
            logging.debug(msg)
