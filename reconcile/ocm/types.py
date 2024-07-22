from __future__ import annotations

from pydantic import (
    BaseModel,
    Extra,
    Field,
)


class OCMClusterAutoscale(BaseModel):
    min_replicas: int
    max_replicas: int


class OCMClusterNetwork(BaseModel):
    type: str | None
    vpc: str
    service: str
    pod: str


class OCMClusterSpec(BaseModel):
    autoscale: OCMClusterAutoscale | None
    channel: str
    disable_user_workload_monitoring: bool | None
    external_id: str | None
    id: str | None
    instance_type: str | None
    multi_az: bool | None
    nodes: int | None
    private: bool
    product: str
    provider: str
    provision_shard_id: str | None
    region: str
    initial_version: str | None
    version: str
    hypershift: bool | None

    class Config:
        extra = Extra.forbid


class OSDClusterSpec(OCMClusterSpec):
    load_balancers: int
    storage: int

    class Config:
        extra = Extra.forbid


class ROSAOcmAwsStsAttrs(BaseModel):
    installer_role_arn: str
    support_role_arn: str
    controlplane_role_arn: str | None
    worker_role_arn: str

    class Config:
        extra = Extra.forbid


class ROSAOcmAwsAttrs(BaseModel):
    creator_role_arn: str
    sts: ROSAOcmAwsStsAttrs | None

    class Config:
        extra = Extra.forbid


class ROSAClusterAWSAccount(BaseModel):
    uid: str
    rosa: ROSAOcmAwsAttrs | None
    billing_account_id: str | None

    class Config:
        extra = Extra.forbid


class ROSAClusterSpec(OCMClusterSpec):
    account: ROSAClusterAWSAccount
    subnet_ids: list[str] | None
    availability_zones: list[str] | None
    oidc_endpoint_url: str | None

    class Config:
        extra = Extra.forbid


class ClusterMachinePool(BaseModel):
    id: str
    instance_type: str
    replicas: int | None
    autoscale: OCMClusterAutoscale | None


class OCMSpec(BaseModel):
    path: str | None
    spec: OSDClusterSpec | ROSAClusterSpec | OCMClusterSpec
    machine_pools: list[ClusterMachinePool] = Field(
        default_factory=list, alias="machinePools"
    )
    network: OCMClusterNetwork
    domain: str | None
    server_url: str = Field("", alias="serverUrl")
    console_url: str = Field("", alias="consoleUrl")
    elb_fqdn: str = Field("", alias="elbFQDN")

    class Config:
        smart_union = True
        # This is need to populate by either console_url or consoleUrl, for instance
        allow_population_by_field_name = True
