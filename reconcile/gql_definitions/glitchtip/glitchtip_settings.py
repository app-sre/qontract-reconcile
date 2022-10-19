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
query GlitchtipSettings {
  settings: app_interface_settings_v1 {
    glitchtip {
      readTimeout
      maxRetries
      mailAddress
    }
  }
}
"""


class GlitchtipSettingsV1(BaseModel):
    read_timeout: int = Field(..., alias="readTimeout")
    max_retries: int = Field(..., alias="maxRetries")
    mail_address: str = Field(..., alias="mailAddress")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppInterfaceSettingsV1(BaseModel):
    glitchtip: Optional[GlitchtipSettingsV1] = Field(..., alias="glitchtip")

    class Config:
        smart_union = True
        extra = Extra.forbid


class GlitchtipSettingsQueryData(BaseModel):
    settings: Optional[list[AppInterfaceSettingsV1]] = Field(..., alias="settings")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> GlitchtipSettingsQueryData:
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
        GlitchtipSettingsQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return GlitchtipSettingsQueryData(**raw_data)
