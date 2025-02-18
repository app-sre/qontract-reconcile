from typing import Any

from pydantic import BaseModel

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE

FLEET_LABELER_LABEL = "FleetLabeler"


class YamlCluster(BaseModel):
    name: str
    server_url: str
    cluster_id: str
    subscription_labels_content: Any


class FleetLabelerUpdates(MergeRequestBase):
    def __init__(
        self,
        path: str,
        content: str,
    ):
        self._path = path
        self._content = content
        self._title = f"[Fleet Labeler] Update cluster inventory for {path}"

        super().__init__()

        self.labels = [AUTO_MERGE, FLEET_LABELER_LABEL]

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._title

    def process(self, gitlab_cli: GitLabApi) -> None:
        msg = "update cluster inventory"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self._path,
            commit_message=msg,
            content=self._content,
        )
