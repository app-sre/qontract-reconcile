import json
from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)


class OcmResponse(BaseModel, ABC):
    @abstractmethod
    def render(self) -> str:
        ...


class OcmRawResponse(OcmResponse):
    response: Any

    def render(self) -> str:
        return json.dumps(self.response)


class OcmUrl(BaseModel):
    name: Optional[str]
    uri: str
    method: str = "POST"
    responses: list[Any] = Field(default_factory=list)

    def add_list_response(
        self, items: list[Any], kind: Optional[str] = None
    ) -> "OcmUrl":
        self.responses.append(
            {
                "kind": f"{kind}List" if kind else "List",
                "items": items,
                "page": 1,
                "size": len(items),
                "total": len(items),
            }
        )
        return self
