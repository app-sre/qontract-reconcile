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
    subscription_id: str
    subscription_labels_content: Any


class FleetLabelerUpdates(MergeRequestBase):
    # Note, this name is used for the branch name that is being created.
    name = "fleet_labeler_updates"

    def __init__(
        self,
        path: str,
        content: str,
    ):
        self._path = path
        self._content = content

        super().__init__()

        self.labels = [AUTO_MERGE, FLEET_LABELER_LABEL]

    @property
    def title(self) -> str:
        return f"[Fleet Labeler] Update cluster inventory for {self._path}"

    @property
    def description(self) -> str:
        return f"""
This is an automatically generated MR by the [fleet-labeler](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/fleet_labeler) integration.

This MR updates the cluster inventory for the fleet label spec defined at {self._path}.

Please do not manually change anything in this MR.
"""

    def process(self, gitlab_cli: GitLabApi) -> None:
        msg = "update cluster inventory"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self._path,
            commit_message=msg,
            content=self._content,
        )
