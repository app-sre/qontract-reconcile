from io import StringIO
from typing import Any

from ruamel.yaml import YAML

from reconcile.change_owners.decision import DecisionCommand
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase

yaml = YAML()
yaml.explicit_start = True
# Lets prevent line wraps
yaml.width = 4096


class ClustersMachinePoolUpdates(MergeRequestBase):
    name = "create_cluster_machine_pool_updates_mr"

    def __init__(self) -> None:
        self.machine_pool_updates: dict[str, list[dict[str, Any]]] = {}

        super().__init__()

        self.labels = []

    def add_machine_pool_update(
        self, cluster_name: str, machine_pool: dict[str, Any]
    ) -> None:
        if cluster_name not in self.machine_pool_updates:
            self.machine_pool_updates[cluster_name] = []
        self.machine_pool_updates[cluster_name].append(machine_pool)

    @property
    def title(self) -> str:
        return f"[{self.name}] machine pool updates"

    @property
    def description(self) -> str:
        return DecisionCommand.APPROVED.value

    def process(self, gitlab_cli: GitLabApi) -> None:
        changes = False
        for cluster_path, machine_pool_updates in self.machine_pool_updates.items():
            cluster_fs_path = f"data{cluster_path}"
            if not machine_pool_updates:
                continue

            raw_file = gitlab_cli.project.files.get(
                file_path=cluster_fs_path, ref=gitlab_cli.main_branch
            )
            content = yaml.load(raw_file.decode())
            if "machinePools" not in content:
                self.cancel("machinePools missing. Nothing to do.")

            for machine_pool in machine_pool_updates:
                for mp in content["machinePools"]:
                    if mp["id"] == machine_pool["id"]:
                        mp.update(machine_pool)
                        changes = True

            with StringIO() as stream:
                yaml.dump(content, stream)
                new_content = stream.getvalue()

            msg = f"update cluster {content['name']} spec fields"
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=cluster_fs_path,
                commit_message=msg,
                content=new_content,
            )

        if not changes:
            self.cancel("Clusters are up to date. Nothing to do.")
