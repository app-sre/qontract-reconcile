from typing import Any

from pydantic import BaseModel

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


class YamlCluster(BaseModel):
    name: str
    server_url: str
    cluster_id: str
    subscription_labels_content: Any


class FleetLabelerUpdates(MergeRequestBase):
    name = "fleet_labeler_updates_mr"

    def __init__(
        self,
        path: str,
        content: str,
    ):
        self._path = path
        self._content = content

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] fleet labeler updates"

    @property
    def description(self) -> str:
        return "fleet labeler updates"

    def process(self, gitlab_cli: GitLabApi) -> None:
        msg = "update upgrade policy clusters"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self._path,
            commit_message=msg,
            content=self._content,
        )
