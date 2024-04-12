from typing import Optional

from pydantic import BaseModel


class TemplateInput(BaseModel):
    collection: str
    collection_hash: str
    enable_auto_approval: bool = False
    labels: Optional[dict]


class TemplateOutput(BaseModel):
    input: Optional[TemplateInput]
    is_new: bool = False
    path: str
    content: str
    auto_approved: bool = False
