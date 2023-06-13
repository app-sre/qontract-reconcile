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
    PRODUCT_ID_ROSA,
    ClusterDetails,
    OCMCapability,
    OCMCluster,
    OCMClusterAWSSettings,
    OCMClusterFlag,
    OCMClusterState,
    OCMClusterVersion,
)
from reconcile.utils.ocm.labels import (
    LabelContainer,
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
    aws_cluster: bool = True,
    sts_cluster: bool = False,
    version: str = "4.13.0",
    cluster_product: str = PRODUCT_ID_ROSA,
    hypershift: bool = False,
) -> OCMCluster:
    aws_config = None
    if aws_cluster:
        aws_config = OCMClusterAWSSettings(sts=OCMClusterFlag(enabled=sts_cluster))
    return OCMCluster(
        id=f"{name}_id",
        external_id=f"{name}_external_id",
        name=name,
        display_name=f"{name}_display_name",
        subscription=OCMModelLink(id=subs_id),
        region=OCMModelLink(id="us-east-1"),
        product=OCMModelLink(id=cluster_product),
        cloud_provider=OCMModelLink(id="aws"),
        state=OCMClusterState.READY,
        managed=True,
        aws=aws_config,
        version=OCMClusterVersion(id=f"openshift-v{version}", raw_id="version"),
        hypershift=OCMClusterFlag(enabled=hypershift),
    )


def build_cluster_details(
    cluster_name: str,
    subscription_labels: Optional[LabelContainer] = None,
    organization_labels: Optional[LabelContainer] = None,
    org_id: str = "org-id",
    aws_cluster: bool = True,
    sts_cluster: bool = False,
    cluster_product: str = PRODUCT_ID_ROSA,
    hypershift: bool = False,
    capabilitites: Optional[dict[str, str]] = None,
) -> ClusterDetails:
    return ClusterDetails(
        ocm_cluster=build_ocm_cluster(
            name=cluster_name,
            subs_id=f"{cluster_name}_subs_id",
            aws_cluster=aws_cluster,
            sts_cluster=sts_cluster,
            cluster_product=cluster_product,
            hypershift=hypershift,
        ),
        organization_id=org_id,
        capabilities={
            name: OCMCapability(
                name=name,
                value=value,
            )
            for name, value in (capabilitites or {}).items()
        },
        subscription_labels=subscription_labels or LabelContainer(),
        organization_labels=organization_labels or LabelContainer(),
    )
