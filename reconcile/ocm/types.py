from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class OCMClusterAutoscale(BaseModel):
    min_replicas: int
    max_replicas: int


class OCMClusterNetwork(BaseModel):
    type: str | None = None
    vpc: str
    service: str
    pod: str


class OCMClusterSpec(BaseModel, extra="forbid"):
    autoscale: OCMClusterAutoscale | None = None
    channel: str
    disable_user_workload_monitoring: bool | None = None
    external_id: str | None = None
    id: str | None = None
    instance_type: str | None = None
    multi_az: bool | None = None
    nodes: int | None = None
    private: bool
    product: str
    provider: str
    provision_shard_id: str | None = None
    region: str
    initial_version: str | None = None
    version: str
    hypershift: bool | None = None
    fips: bool = False

    @field_validator("fips", mode="before")
    @classmethod
    def set_fips_default(cls, v: bool | None) -> bool:
        return v or False


class OSDClusterSpec(OCMClusterSpec, extra="forbid"):
    load_balancers: int
    storage: int


class ROSAOcmAwsStsAttrs(BaseModel, extra="forbid"):
    installer_role_arn: str
    support_role_arn: str
    controlplane_role_arn: str | None = None
    worker_role_arn: str


class ROSAOcmAwsAttrs(BaseModel, extra="forbid"):
    creator_role_arn: str
    sts: ROSAOcmAwsStsAttrs | None = None


class ROSAClusterAWSAccount(BaseModel, extra="forbid"):
    uid: str
    rosa: ROSAOcmAwsAttrs | None = None
    billing_account_id: str | None = None


class ROSAClusterSpec(OCMClusterSpec, extra="forbid"):
    account: ROSAClusterAWSAccount
    subnet_ids: list[str] | None = None
    availability_zones: list[str] | None = None
    oidc_endpoint_url: str | None = None


class ClusterMachinePool(BaseModel):
    id: str
    instance_type: str
    replicas: int | None = None
    autoscale: OCMClusterAutoscale | None = None


class OCMSpec(BaseModel, validate_by_name=True, validate_by_alias=True):
    path: str | None = None
    spec: OSDClusterSpec | ROSAClusterSpec | OCMClusterSpec
    machine_pools: list[ClusterMachinePool] = Field(
        default_factory=list, alias="machinePools"
    )
    network: OCMClusterNetwork
    domain: str | None = None
    server_url: str = Field("", alias="serverUrl")
    console_url: str = Field("", alias="consoleUrl")
    elb_fqdn: str = Field("", alias="elbFQDN")
