from typing import Any

from deepdiff import DeepHash
from pydantic import BaseModel

from reconcile.gql_definitions.templating.template_collection import (
    TemplateV1,
)


class TemplateInput(BaseModel):
    collection: str
    templates: list[TemplateV1] = []
    variables: list[dict[str, Any]] = []
    collection_hash: str = ""
    enable_auto_approval: bool = False
    labels: list[str] = []

    def calc_template_hash(self) -> str:
        if not self.collection_hash:
            hashable = {
                "templates": sorted(self.templates, key=lambda x: x.name),
                "variables": self.variables,
            }
            self.collection_hash = DeepHash(hashable)[hashable]
        return self.collection_hash


class TemplateOutput(BaseModel):
    input: TemplateInput
    is_new: bool = False
    path: str
    content: str
    auto_approved: bool = False
