from collections import defaultdict
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Optional

from reconcile.cna.assets.asset_factory import asset_factory_from_schema
from reconcile.cna.client import CNAClient
from reconcile.cna.state import State
from reconcile.gql_definitions.cna.queries.cna_provisioners import (
    CNAExperimentalProvisionerV1,
)
from reconcile.gql_definitions.cna.queries.cna_provisioners import (
    query as cna_provisioners_query,
)
from reconcile.gql_definitions.cna.queries.cna_resources import (
    NamespaceCNAssetV1,
    NamespaceV1,
)
from reconcile.gql_definitions.cna.queries.cna_resources import (
    query as namespaces_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)
from reconcile.utils.semver_helper import make_semver

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
            for provider in namespace.external_resources or []:
                # TODO: this should probably be filtered within the query already
                if not isinstance(provider, NamespaceCNAssetV1):
                    continue
                for resource in provider.resources or []:
                    self._desired_states[provider.provisioner.name].add_asset(
                        asset_factory_from_schema(resource)
                    )

    def assemble_current_states(self):
        self._current_states = defaultdict(State)
        for name, client in self._cna_clients.items():
            cnas = client.list_assets()
            state = State()
            state.add_raw_data(cnas)
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
