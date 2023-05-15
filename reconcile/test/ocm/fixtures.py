import json
from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)

from reconcile.utils.ocm.base import OCMModelLink
from reconcile.utils.ocm.clusters import (
    OCMCluster,
    OCMClusterState,
)
from reconcile.utils.ocm.labels import (
    OCMLabel,
    OCMOrganizationLabel,
)


class OcmResponse(BaseModel, ABC):
    @abstractmethod
    def render(self) -> str:
        ...


class OcmRawResponse(OcmResponse):
    response: Any

    def render(self) -> str:
        return json.dumps(self.response)


class OcmUrl(BaseModel):
    name: Optional[str]
    uri: str
    method: str = "POST"
    responses: list[Any] = Field(default_factory=list)

    def add_list_response(
        self, items: list[Any], kind: Optional[str] = None
    ) -> "OcmUrl":
        self.responses.append(
            {
                "kind": f"{kind}List" if kind else "List",
                "items": items,
                "page": 1,
                "size": len(items),
                "total": len(items),
            }
        )
        return self


def build_label(key: str, value: str) -> OCMLabel:
    return OCMLabel(
        created_at="2021-09-01T00:00:00Z",
        updated_at="2021-09-01T00:00:00Z",
        id=f"{key}_id",
        internal=False,
        href=f"https://ocm/label/{key}_id",
        key=key,
        value=value,
        type="Subscription",
    )


def build_organization_label(key: str, value: str, org_id: str = "org-id") -> OCMLabel:
    return OCMOrganizationLabel(
        created_at="2021-09-01T00:00:00Z",
        updated_at="2021-09-01T00:00:00Z",
        id=f"{key}_id",
        internal=False,
        href=f"https://ocm/label/{key}_id",
        key=key,
        value=value,
        type="Organization",
        organization_id=org_id,
    )


def build_ocm_cluster(
    name: str,
    subs_id: str = "subs_id",
) -> OCMCluster:
    return OCMCluster(
        id=f"{name}_id",
        external_id=f"{name}_external_id",
        name=name,
        display_name=f"{name}_display_name",
        subscription=OCMModelLink(id=subs_id),
        region=OCMModelLink(id="us-east-1"),
        product=OCMModelLink(id="OCP"),
        cloud_provider=OCMModelLink(id="aws"),
        state=OCMClusterState.READY,
        openshift_version="4.12.0",
        managed=True,
    )
