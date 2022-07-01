from pydantic import BaseModel, Field, Extra
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


class ROSAClusterSpec(OCMClusterSpec):
    pass


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
