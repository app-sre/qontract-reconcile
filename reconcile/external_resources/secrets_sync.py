import base64
import dataclasses
import json
import logging
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from datetime import datetime
from hashlib import shake_128
from typing import Any, Optional, cast

from pydantic import BaseModel
from sretoolbox.utils import threaded

from reconcile.external_resources.meta import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
)
from reconcile.external_resources.model import ExternalResourceKey
from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.utils.differ import DiffPair, diff_mappings
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

SECRET_ANN_PREFIX = "external-resources"
SECRET_ANN_PROVISION_PROVIDER = SECRET_ANN_PREFIX + "/provision_provider"
SECRET_ANN_PROVISIONER = SECRET_ANN_PREFIX + "/provisioner_name"
SECRET_ANN_PROVIDER = SECRET_ANN_PREFIX + "/provider"
SECRET_ANN_IDENTIFIER = SECRET_ANN_PREFIX + "/identifier"
SECRET_UPDATED_AT = SECRET_ANN_PREFIX + "/updated_at"
SECRET_UPDATED_AT_TIMEFORMAT = "%d/%m/%Y %H:%M:%S"


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

    def _del_secret_updated_at(self, spec: ExternalResourceSpec) -> None:
        data = cast(dict[str, str], spec.secret)
        del data[SECRET_UPDATED_AT]

    def _annotate(self, spec: ExternalResourceSpec) -> None:
        try:
            annotations = json.loads(spec.resource["annotations"])
        except Exception:
            annotations = {}
        annotations[SECRET_ANN_PROVISION_PROVIDER] = spec.provision_provider
        annotations[SECRET_ANN_PROVISIONER] = spec.provisioner_name
        annotations[SECRET_ANN_PROVIDER] = spec.provider
        annotations[SECRET_ANN_IDENTIFIER] = spec.identifier
        annotations[SECRET_UPDATED_AT] = spec.secret[SECRET_UPDATED_AT]
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

    def _copy_spec(self, spec: ExternalResourceSpec) -> ExternalResourceSpec:
        copy = dataclasses.replace(spec)
        copy.secret = dict(spec.secret)
        return copy

    def sync_secrets(
        self, specs: Iterable[ExternalResourceSpec]
    ) -> list[ExternalResourceSpec]:
        self._populate_secret_data(specs)

        # Updated_at attribute must be removed before syncing the secret
        # but is needed afterwards. All specs are copied to preserve the originals.
        to_sync_specs = [
            self._copy_spec(spec) for spec in self._specs_with_secret(specs)
        ]

        for spec in to_sync_specs:
            self._annotate(spec)
            self._del_secret_updated_at(spec)
            self._add_secret_to_ri(spec)

        ocmap = self._init_ocmap(to_sync_specs)
        threaded.run(
            self.reconcile_data,
            self.ri,
            thread_pool_size=self.thread_pool_size,
            ocmap=ocmap,
        )

        return []

    def _current_secret_is_newer(self, i: DiffPair) -> bool:
        try:
            current = datetime.strptime(
                i.current.annotations[SECRET_UPDATED_AT],
                SECRET_UPDATED_AT_TIMEFORMAT,
            )
            desired = datetime.strptime(
                i.desired.annotations[SECRET_UPDATED_AT],
                SECRET_UPDATED_AT_TIMEFORMAT,
            )
            return current > desired
        except KeyError:
            return False

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
        items_to_update = [
            i.desired
            for i in diff.change.values()
            if not self._current_secret_is_newer(i)
        ] + list(diff.add.values())

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

            data[SECRET_UPDATED_AT] = datetime.now().strftime(
                SECRET_UPDATED_AT_TIMEFORMAT
            )
            spec.secret = data

    def _delete_source_secret(self, spec: ExternalResourceSpec) -> None:
        secret_name = self._get_spec_outputs_secret_name(spec)
        logging.debug("Deleting secret " + secret_name)
        self.oc.delete(namespace=self.namespace, kind="Secret", name=secret_name)

    def _write_secret_to_vault(self, spec: ExternalResourceSpec) -> None:
        secret_path = f"{self.vault_path}/{spec.cluster_name}/{spec.namespace_name}/{spec.identifier}"
        stringified_secret = {k: str(v) for k, v in spec.secret.items()}
        desired_secret = {"path": secret_path, "data": stringified_secret}
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
                "All specs reconciled in this iteration are marked as pending secret syncronization\n%s",
                e,
            )
            return list(specs)

        for spec in self._specs_with_secret(specs):
            try:
                self._write_secret_to_vault(spec)
                self._delete_source_secret(spec)
            except Exception as e:
                key = ExternalResourceKey.from_spec(spec)
                logging.error("Error writting Secret to Vault. Key: %s.\n%s", key, e)
                specs_with_error.append(spec)
                continue

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
            spec.secret = data
        except Exception:
            msg = f"Error getting secret from vault, skipping. [{secret_path}]"
            logging.info(msg)
