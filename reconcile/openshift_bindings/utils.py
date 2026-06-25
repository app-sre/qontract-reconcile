from __future__ import annotations

from typing import TYPE_CHECKING

import reconcile.openshift_base as ob
from reconcile.utils.sharding import is_in_shard

if TYPE_CHECKING:
    from reconcile.gql_definitions.common.app_interface_roles import NamespaceV1
    from reconcile.gql_definitions.common.namespaces import (
        NamespaceV1 as CommonNamespaceV1,
    )


def is_valid_namespace(
    namespace: NamespaceV1 | CommonNamespaceV1,
) -> bool:
    return (
        bool(namespace.managed_roles)
        and is_in_shard(f"{namespace.cluster.name}/{namespace.name}")
        and not ob.is_namespace_deleted(namespace.model_dump(by_alias=True))
    )
