"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from typing import (  # noqa: F401 # pylint: disable=W0611
    Any,
    Callable,
    Optional,
    Union,
)

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)


DEFINITION = """
query VaultPolicies {
    policy: vault_policies_v1 {
        name
        instance {
            name
        }
        rules
    }
}
"""


class VaultInstanceV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class VaultPolicyV1(BaseModel):
    name: str = Field(..., alias="name")
    instance: VaultInstanceV1 = Field(..., alias="instance")
    rules: str = Field(..., alias="rules")

    class Config:
        smart_union = True
        extra = Extra.forbid


class VaultPoliciesQueryData(BaseModel):
    policy: Optional[list[VaultPolicyV1]] = Field(..., alias="policy")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> VaultPoliciesQueryData:
    """
    This is a convenience function which queries and parses the data into
    concrete types. It should be compatible with most GQL clients.
    You do not have to use it to consume the generated data classes.
    Alternatively, you can also mime and alternate the behavior
    of this function in the caller.

    Parameters:
        query_func (Callable): Function which queries your GQL Server
        kwargs: optional arguments that will be passed to the query function

    Returns:
        VaultPoliciesQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return VaultPoliciesQueryData(**raw_data)
