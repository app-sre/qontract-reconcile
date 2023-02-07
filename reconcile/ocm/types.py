from __future__ import annotations

from typing import (
    Optional,
    Union,
)

from pydantic import (
    BaseModel,
    Extra,
    Field,
)


class OCMClusterAutoscale(BaseModel):
    min_replicas: int
    max_replicas: int


class OCMClusterNetwork(BaseModel):
    type: Optional[str]
    vpc: str
    service: str
    pod: str


class OCMClusterSpec(BaseModel):
    autoscale: Optional[OCMClusterAutoscale]
    channel: str
    disable_user_workload_monitoring: Optional[bool]
    external_id: Optional[str]
    id: Optional[str]
    instance_type: str
    multi_az: bool
    nodes: Optional[int]
    private: bool
    product: str
    provider: str
    provision_shard_id: Optional[str]
    region: str
    initial_version: Optional[str]
    version: str
    hypershift: Optional[bool]

    class Config:
        extra = Extra.forbid


class OSDClusterSpec(OCMClusterSpec):
    load_balancers: int
    storage: int

    class Config:
        extra = Extra.forbid


class ROSAOcmAwsAttrs(BaseModel):
    creator_role_arn: str
    installer_role_arn: str
    support_role_arn: str
    controlplane_role_arn: str
    worker_role_arn: str

    class Config:
        extra = Extra.forbid


class ROSAClusterAWSAccount(BaseModel):
    uid: str
    rosa: ROSAOcmAwsAttrs

    class Config:
        extra = Extra.forbid


class ROSAClusterSpec(OCMClusterSpec):
    account: ROSAClusterAWSAccount
    subnet_ids: Optional[list[str]]
    availability_zones: Optional[list[str]]

    class Config:
        extra = Extra.forbid


class OCMSpec(BaseModel):
    path: Optional[str]
    spec: Union[OSDClusterSpec, ROSAClusterSpec, OCMClusterSpec]
    network: OCMClusterNetwork
    domain: Optional[str]
    server_url: str = Field("", alias="serverUrl")
    console_url: str = Field("", alias="consoleUrl")
    elb_fqdn: str = Field("", alias="elbFQDN")

    class Config:
        smart_union = True
        # This is need to populate by either console_url or consoleUrl, for instance
        allow_population_by_field_name = True


class OCMOidcIdp(BaseModel):
    id: Optional[str] = None
    cluster: str
    name: str
    client_id: str
    client_secret: Optional[str] = None
    issuer: str
    email_claims: list[str]
    name_claims: list[str]
    username_claims: list[str]
    groups_claims: list[str]

    def __lt__(self, other: OCMOidcIdp) -> bool:
        return self.cluster < other.cluster

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OCMOidcIdp):
            raise NotImplementedError("Cannot compare to non OCMOidcIdp objects.")
        return self.cluster == other.cluster and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.cluster + self.name + self.client_id)

    def differ(self, other: OCMOidcIdp) -> bool:
        return (
            self.client_id != other.client_id
            or self.issuer != other.issuer
            or self.email_claims != other.email_claims
            or self.username_claims != other.username_claims
            or self.name_claims != other.name_claims
            or self.groups_claims != other.groups_claims
        )
