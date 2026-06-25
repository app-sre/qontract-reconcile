from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.ocm_environments import query
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment


def get_ocm_environments() -> list[OCMEnvironment]:
    data = query(gql.get_api().query)
    return list(data.environments or [])
