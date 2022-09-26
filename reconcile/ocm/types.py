from pydantic import BaseModel, Field, Extra, validator
from typing import Optional, Union


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

    class Config:
        extra = Extra.forbid


class OSDClusterSpec(OCMClusterSpec):
    load_balancers: int
    storage: int

    class Config:
        extra = Extra.forbid


class ROSAAWSAttrs(BaseModel):
    creator_role_arn: str
    installer_role_arn: Optional[str]
    support_role_arn: Optional[str]
    controlplane_role_arn: Optional[str]
    worker_role_arn: Optional[str]

    class Config:
        extra = Extra.forbid


class ROSAClusterAWSAccount(BaseModel):
    uid: str
    rosa: ROSAAWSAttrs

    @validator("rosa", always=True)
    @classmethod
    def set_rosa(cls, rosa: ROSAAWSAttrs, values):
        if not rosa.installer_role_arn:
            rosa.installer_role_arn = (
                f"arn:aws:iam::{values['uid']}:role/ManagedOpenShift-Installer-Role"
            )

        if not rosa.support_role_arn:
            rosa.support_role_arn = (
                f"arn:aws:iam::{values['uid']}:role/ManagedOpenShift-Support-Role"
            )

        if not rosa.controlplane_role_arn:
            rosa.controlplane_role_arn = (
                f"arn:aws:iam::{values['uid']}:role/ManagedOpenShift-ControlPlane-Role"
            )

        if not rosa.worker_role_arn:
            rosa.worker_role_arn = (
                f"arn:aws:iam::{values['uid']}:role/ManagedOpenShift-Worker-Role"
            )

        return rosa

    class Config:
        extra = Extra.forbid


class ROSAClusterSpec(OCMClusterSpec):
    account: ROSAClusterAWSAccount

    class Config:
        extra = Extra.forbid


class OCMSpec(BaseModel):
    path: Optional[str]
    spec: Union[OSDClusterSpec, ROSAClusterSpec]
    network: OCMClusterNetwork
    domain: Optional[str]
    server_url: str = Field(None, alias="serverUrl")
    console_url: str = Field(None, alias="consoleUrl")
    elb_fqdn: str = Field(None, alias="elbFQDN")

    class Config:
        smart_union = True
        # This is need to populate by either console_url or consoleUrl, for instance
        allow_population_by_field_name = True
