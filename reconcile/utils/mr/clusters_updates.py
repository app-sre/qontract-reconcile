from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.ruamel import create_ruamel_instance, dump_yaml

from reconcile.change_owners.decision import DecisionCommand
from reconcile.utils.mr.base import MergeRequestBase

if TYPE_CHECKING:
    from collections.abc import Mapping

    from reconcile.utils.gitlab_api import GitLabApi

yaml = create_ruamel_instance(explicit_start=True)


class CreateClustersUpdates(MergeRequestBase):
    name = "create_clusters_updates_mr"

    def __init__(self, clusters_updates: Mapping[str, dict[str, Any]]):
        self.clusters_updates = clusters_updates

        super().__init__()

        self.labels = []

    @property
    def title(self) -> str:
        return f"[{self.name}] clusters updates"

    @property
    def description(self) -> str:
        return DecisionCommand.APPROVED.value

    def process(self, gitlab_cli: GitLabApi) -> None:
        changes = False
        for cluster_name, cluster_updates in self.clusters_updates.items():
            if not cluster_updates:
                continue

            cluster_path = cluster_updates.pop("path")
            raw_file = gitlab_cli.get_raw_file(
                project=gitlab_cli.project,
                path=cluster_path,
                ref=gitlab_cli.main_branch,
            )
            content = yaml.load(raw_file)
            if "spec" not in content:
                self.cancel("Spec missing. Nothing to do.")

            # check that there are updates to be made
            if (
                cluster_updates["spec"].items() <= content["spec"].items()
                and cluster_updates["root"].items() <= content.items()
            ):
                continue
            changes = True

            content["spec"].update(cluster_updates["spec"])
            # Since spec is a dictionary we can't simply do
            # content.update(cluster_updates) :(
            content.update(cluster_updates["root"])

            new_content = dump_yaml(yaml, content)

            msg = f"update cluster {cluster_name} spec fields"
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=cluster_path,
                commit_message=msg,
                content=new_content,
            )

        if not changes:
            self.cancel("Clusters are up to date. Nothing to do.")
