from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultInstanceV1,
    query,
)
from reconcile.utils import gql


def get_vault_instances() -> list[VaultInstanceV1]:
    data = query(gql.get_api().query)
    return list(data.vault_instances or [])
