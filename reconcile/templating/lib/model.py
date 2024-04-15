from pydantic import BaseModel


class TemplateInput(BaseModel):
    collection: str
    collection_hash: str
    enable_auto_approval: bool = False
    labels: list[str] = []


class TemplateOutput(BaseModel):
    input: TemplateInput
    is_new: bool = False
    path: str
    content: str
    auto_approved: bool = False
