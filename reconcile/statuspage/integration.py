from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.statuspage import statuspages
from reconcile.statuspage.state import S3ComponentBindingState
from reconcile.utils import gql
from reconcile.utils.state import init_state

if TYPE_CHECKING:
    from reconcile.gql_definitions.statuspage.statuspages import StatusPageV1
    from reconcile.utils.secret_reader import (
        SecretReaderBase,
    )


def get_status_pages() -> list[StatusPageV1]:
    return statuspages.query(gql.get_api().query).status_pages or []


def get_binding_state(
    integration: str, secret_reader: SecretReaderBase
) -> S3ComponentBindingState:
    state = init_state(
        integration=integration,
        secret_reader=secret_reader,
    )
    return S3ComponentBindingState(state)
