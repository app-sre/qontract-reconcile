"""High-level Internal Groups client (Layer 1)."""

from __future__ import annotations

from qontract_utils.internal_groups_api.api import InternalGroupsApi, NotFoundError
from qontract_utils.internal_groups_api.models import Group

__all__ = ["InternalGroupsApi", "InternalGroupsClient", "NotFoundError"]


class InternalGroupsClient:
    """High-level Internal Groups client."""

    def __init__(
        self,
        api_url: str,
        issuer_url: str,
        client_id: str,
        client_secret: str,
        api_class: type[InternalGroupsApi] = InternalGroupsApi,
    ) -> None:
        self._api = api_class(api_url, issuer_url, client_id, client_secret)

    def close(self) -> None:
        self._api.close()

    def group(self, name: str) -> Group:
        with self._api as api:
            return Group(**api.group(name))

    def create_group(self, group: Group) -> Group:
        with self._api as api:
            return Group(**api.create_group(data=group.model_dump(by_alias=True)))

    def delete_group(self, name: str) -> None:
        with self._api as api:
            api.delete_group(name)

    def update_group(self, group: Group) -> Group:
        with self._api as api:
            return Group(
                **api.update_group(
                    name=group.name,
                    data=group.model_dump(by_alias=True),
                )
            )
