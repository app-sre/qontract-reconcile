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
