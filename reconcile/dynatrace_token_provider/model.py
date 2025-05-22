from pydantic import BaseModel

from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)


class DynatraceAPIToken(BaseModel):
    token: str
    id: str
    name: str
    secret_key: str


class K8sSecret(BaseModel):
    namespace_name: str
    secret_name: str
    dt_api_url: str
    tokens: list[DynatraceAPIToken]


class TokenSpecTenantBinding(BaseModel):
    spec: DynatraceTokenProviderTokenSpecV1
    tenant_id: str


class Cluster(BaseModel):
    id: str
    external_id: str
    organization_id: str
    is_hcp: bool
    dt_token_bindings: list[TokenSpecTenantBinding]
