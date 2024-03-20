from typing import Optional

from pydantic import BaseModel


class TemplateInput(BaseModel):
    collection: str
    template_hash: str


class TemplateOutput(BaseModel):
    input: Optional[TemplateInput]
    path: str
    content: str
