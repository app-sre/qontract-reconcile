from pydantic import BaseModel


class DynatraceAPIToken(BaseModel):
    token: str
    id: str
    name: str
    secret_key: str


class K8sSecret(BaseModel):
    namespace_name: str
    secret_name: str
    tokens: list[DynatraceAPIToken]


class TokenSpecTenantBinding(BaseModel):
    spec_name: str
    tenant_id: str


class Cluster(BaseModel):
    id: str
    external_id: str
    organization_id: str
    is_hcp: bool
    dt_token_bindings: list[TokenSpecTenantBinding]
