from collections import defaultdict
import logging
from typing import Iterable, Mapping, Optional
from reconcile.cna.client import CNAClient
from reconcile.cna.state import State

from reconcile.utils import gql
from reconcile.utils.external_resources import (
    get_external_resource_specs_for_namespace,
    PROVIDER_CNA_EXPERIMENTAL,
)
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.gql_definitions.cna.queries.cna_provisioners import (
    CNAExperimentalProvisionerV1,
    query as cna_provisioners_query,
)
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNAssetV1,
    NamespaceV1,
    query as namespaces_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.secret_reader import SecretReaderBase, create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.cna.assets.asset import UnknownAssetTypeError, AssetError
from reconcile.cna.assets.asset_factory import (
    asset_factory_from_schema,
    asset_factory_from_raw_data,
)


QONTRACT_INTEGRATION = "cna_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class CNAConfigException(Exception):
    pass


class CNAIntegration:
    def __init__(
        self,
        cna_clients: Mapping[str, CNAClient],
        namespaces: Iterable[NamespaceV1],
        desired_states: Optional[Mapping[str, State]] = None,
        current_states: Optional[Mapping[str, State]] = None,
    ):
        self._cna_clients = cna_clients
        self._namespaces = namespaces
        self._desired_states = desired_states if desired_states else defaultdict(State)
        self._current_states = current_states if current_states else defaultdict(State)

    def assemble_desired_states(self):
        self._desired_states = defaultdict(State)
        for namespace in self._namespaces:
            for spec in get_external_resource_specs_for_namespace(
                namespace, CNAssetV1, PROVIDER_CNA_EXPERIMENTAL
            ):
                resolved_spec = spec.resolve()
                asset = asset_factory_from_schema(resolved_spec)
                self._desired_states[spec.provisioner_name].add_asset(asset)

    def assemble_current_states(self):
        self._current_states = defaultdict(State)
        for name, client in self._cna_clients.items():
            state = State()
            for raw_asset in client.list_assets_for_creator(
                client.service_account_name()
            ):
                try:
                    state.add_asset(
                        asset_factory_from_raw_data(
                            raw_asset,
                        )
                    )
                except UnknownAssetTypeError as e:
                    logging.warning(e)
                except AssetError as e:
                    # TODO: remember this somehow in the state so we don't try to update/create this asset but skip it instead
                    logging.error(e)
            self._current_states[name] = state

    def provision(self, dry_run: bool = False):
        for provisioner_name, cna_client in self._cna_clients.items():
            desired_state = self._desired_states[provisioner_name]
            current_state = self._current_states[provisioner_name]

            additions = desired_state - current_state
            for asset in additions:
                cna_client.create(asset=asset, dry_run=dry_run)

            deletions = current_state - desired_state
            for asset in deletions:
                cna_client.delete(asset=asset, dry_run=dry_run)

            updates = current_state.required_updates_to_reach(desired_state)
            for assets in updates:
                cna_client.update(asset=assets, dry_run=dry_run)


def build_cna_clients(
    secret_reader: SecretReaderBase,
    cna_provisioners: list[CNAExperimentalProvisionerV1],
) -> dict[str, CNAClient]:
    clients: dict[str, CNAClient] = {}
    for provisioner in cna_provisioners:
        if not provisioner.ocm.access_token_client_secret:
            raise CNAConfigException(
                f"No access_token_client_secret for provisioner {provisioner.name}"
            )
        secret_data = secret_reader.read_all_secret(
            provisioner.ocm.access_token_client_secret
        )
        # todo verify schema compatibility
        ocm_client = OCMBaseClient(
            url=provisioner.ocm.url,
            access_token_client_secret=secret_data["client_secret"],
            access_token_url=provisioner.ocm.access_token_url,
            access_token_client_id=provisioner.ocm.access_token_client_id,
        )
        clients[provisioner.name] = CNAClient(
            ocm_client=ocm_client,
        )
    return clients


def run(
    dry_run: bool,
    # TODO: Threadpool not used yet - will be used once we understand scopes in more detail
    thread_pool_size: int,
    defer=None,
) -> None:
    settings = get_app_interface_vault_settings()
    use_vault = (settings or False) and settings.vault
    secret_reader = create_secret_reader(use_vault=use_vault)

    query_func = gql.get_api().query
    cna_provisioners = cna_provisioners_query(query_func).cna_provisioners or []
    namespaces = namespaces_query(query_func).namespaces or []

    cna_clients = build_cna_clients(
        secret_reader=secret_reader, cna_provisioners=cna_provisioners
    )

    integration = CNAIntegration(cna_clients=cna_clients, namespaces=namespaces)
    integration.assemble_current_states()
    integration.assemble_desired_states()
    integration.provision(dry_run=dry_run)
