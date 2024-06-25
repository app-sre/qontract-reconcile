from deepdiff import DeepHash
from pydantic import BaseModel


class TemplateOutput(BaseModel):
    is_new: bool = False
    path: str
    content: str
    auto_approved: bool = False


class TemplateResult(BaseModel):
    collection: str
    enable_auto_approval: bool = False
    labels: list[str] = []
    outputs: list[TemplateOutput] = []

    def calc_result_hash(self) -> str:
        hashable = {o.path: o for o in self.outputs}
        return DeepHash(hashable)[hashable]
