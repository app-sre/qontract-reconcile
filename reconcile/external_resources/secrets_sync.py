import base64
import json
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from hashlib import shake_128
from typing import Any, Optional, cast

from pydantic import BaseModel
from sretoolbox.utils import retry

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
        vault_path: str,
        vault_client: VaultClient,
    ) -> None:
        self.secrets_reader = secrets_reader
        self.ri = ri
        self.vault_path = vault_path
        self.vault_client = cast(_VaultClient, vault_client)

    @abstractmethod
    def _populate_secret_data(self, specs: Iterable[ExternalResourceSpec]) -> None:
        raise NotImplementedError()

    def _populate_annotations(self, spec: ExternalResourceSpec) -> None:
        try:
            annotations = json.loads(spec.resource["annotations"])
        except Exception:
            annotations = {}

        annotations["provision_provider"] = spec.provision_provider
        annotations["provisioner"] = spec.provisioner_name
        annotations["provider"] = spec.provider
        annotations["identifier"] = spec.identifier

        spec.resource["annotations"] = json.dumps(annotations)

    def _initialize_ri(
        self,
        ri: ResourceInventory,
        specs: Iterable[ExternalResourceSpec],
    ) -> None:
        for spec in specs:
            ri.initialize_resource_type(
                spec.cluster_name, spec.namespace_name, "Secret"
            )
            ri.add_desired(
                spec.cluster_name,
                spec.namespace_name,
                "Secret",
                name=spec.output_resource_name,
                value=spec.build_oc_secret(
                    QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
                ),
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

    @retry()
    def _write_secrets_to_vault(self, spec: ExternalResourceSpec) -> None:
        if spec.secret:
            secret_path = f"{self.vault_path}/{QONTRACT_INTEGRATION}/{spec.cluster_name}/{spec.namespace_name}/{spec.output_resource_name}"
            stringified_secret = {k: str(v) for k, v in spec.secret.items()}
            desired_secret = {"path": secret_path, "data": stringified_secret}
            self.vault_client.write(desired_secret, decode_base64=False)

    def sync_secrets(self, specs: Iterable[ExternalResourceSpec]) -> None:
        self._populate_secret_data(specs)
        ri = ResourceInventory()
        self._initialize_ri(ri, specs)
        ocmap = self._init_ocmap(specs)
        for item in ri:
            self.reconcile_data(item, ri, ocmap)

    def reconcile_data(
        self,
        ri_item: tuple[str, str, str, Mapping[str, Any]],
        ri: ResourceInventory,
        ocmap: OCMap,
    ) -> None:
        cluster, namespace, kind, data = ri_item
        oc = ocmap.get_cluster(cluster)
        names = list(data["desired"].keys())

        items = oc.get_items("Secret", namespace=namespace, resource_names=names)
        for item in items:
            obj = OpenshiftResource(
                body=item,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            ri.add_current(cluster, namespace, kind, name=obj.name, value=obj)

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
    ):
        super().__init__(ri, secrets_reader, vault_path, vault_client)

        self.cluster = cluster
        self.namespace = namespace
        self.oc = oc
        self.source_secrets: list[str] = []

    def _get_spec_hash(self, spec: ExternalResourceSpec) -> str:
        secret_key = f"{spec.provision_provider}-{spec.provisioner_name}-{spec.provider}-{spec.identifier}"
        return shake_128(secret_key.encode("utf-8")).hexdigest(16)

    def _populate_secret_data(self, specs: Iterable[ExternalResourceSpec]) -> None:
        if not specs:
            return
        secrets_map = {
            "external-resources-output-" + self._get_spec_hash(spec): spec
            for spec in specs
        }
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

        self.source_secrets = list(secrets_map.keys())

    def _delete_source_secrets(self) -> None:
        for secret_name in self.source_secrets:
            print("Deleting secret " + secret_name)
            self.oc.delete(namespace=self.namespace, kind="Secret", name=secret_name)

    def sync_secrets(self, specs: Iterable[ExternalResourceSpec]) -> None:
        super().sync_secrets(specs)
        self._delete_source_secrets()


def build_incluster_secrets_reconciler(
    cluster: str, namespace: str, secrets_reader: SecretReaderBase, vault_path: str
) -> InClusterSecretsReconciler:
    ri = ResourceInventory()
    ocmap = init_oc_map_from_clusters(
        clusters=[c for c in get_clusters_minimal() if c.name == cluster],
        secret_reader=secrets_reader,
        integration=QONTRACT_INTEGRATION,
    )
    oc = ocmap.get_cluster(cluster)
    vault_client = VaultClient()
    return InClusterSecretsReconciler(
        cluster=cluster,
        namespace=namespace,
        ri=ri,
        oc=oc,
        vault_path=vault_path,
        vault_client=vault_client,
        secrets_reader=secrets_reader,
    )
