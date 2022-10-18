from collections import defaultdict
from typing import Iterable, Mapping
from reconcile.cna.assets import NullAsset
from reconcile.cna.client import CNAClient
from reconcile.cna.state import State

from reconcile.utils import gql
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.gql_definitions.cna.queries.cna_provisioners import (
    CNAProvisionerV1,
    query as cna_provisioners_query,
)
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullResourceV1,
    NamespaceCNAResourceV1,
    NamespaceV1,
    query as namespaces_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.secret_reader import SecretReaderBase, create_secret_reader
from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = "cna_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtfcf"


class CNAConfigException(Exception):
    pass


def build_cna_clients(
    secret_reader: SecretReaderBase, cna_provisioners: list[CNAProvisionerV1]
) -> dict[str, CNAClient]:
    clients: dict[str, CNAClient] = {}
    for provisioner in cna_provisioners:
        if not provisioner.ocm.offline_token:
            raise CNAConfigException(
                f"No offline_token for provisioner {provisioner.name}"
            )
        secret_data = secret_reader.read_all_secret(provisioner.ocm.offline_token)
        ocm_client = OCMBaseClient(
            url=provisioner.ocm.url,
            offline_token=secret_data["offline_token"],
            access_token_url=provisioner.ocm.access_token_url,
            access_token_client_id=provisioner.ocm.access_token_client_id,
        )
        clients[provisioner.name] = CNAClient(
            ocm_client=ocm_client,
        )
    return clients


def assemble_desired_states_by_provisioner(
    namespaces: Iterable[NamespaceV1],
) -> dict[str, State]:
    ans: dict[str, State] = defaultdict(State)
    for namespace in namespaces:
        for provider in namespace.external_resources or []:
            # TODO: this should probably be filtered within the query already
            if not isinstance(provider, NamespaceCNAResourceV1):
                continue
            for resource in provider.resources or []:
                if isinstance(resource, CNANullResourceV1):
                    null_asset = NullAsset.from_query_class(resource)
                    ans[provider.provisioner.name].add_null_asset(null_asset)
    return ans


def assemble_actual_states_by_provisioner(
    cna_clients: Mapping[str, CNAClient]
) -> dict[str, State]:
    ans = {}
    for name, client in cna_clients.items():
        cnas = client.list_assets()
        state = State()
        state.add_raw_data(cnas)
        ans[name] = state
    return ans


def create(cna_client: CNAClient, additions: State):
    for resource in additions:
        cna_client.create(resource)


def delete(cna_client: CNAClient, deletions: State):
    for resource in deletions:
        cna_client.delete(resource)


def run(
    dry_run: bool,
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
    desired_states = assemble_desired_states_by_provisioner(namespaces=namespaces)
    actual_states = assemble_actual_states_by_provisioner(cna_clients=cna_clients)

    for provisioner_name, cna_client in cna_clients.items():
        desired_state = desired_states[provisioner_name]
        actual_state = actual_states[provisioner_name]

        additions = desired_state - actual_state
        create(additions=additions, cna_client=cna_client)

        deletions = actual_state - desired_state
        delete(deletions=deletions, cna_client=cna_client)
