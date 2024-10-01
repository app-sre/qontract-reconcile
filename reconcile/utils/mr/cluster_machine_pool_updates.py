from io import StringIO
from typing import Any

from reconcile.change_owners.decision import DecisionCommand
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.ruamel import create_ruamel_instance


class ClustersMachinePoolUpdates(MergeRequestBase):
    name = "create_cluster_machine_pool_updates_mr"

    def __init__(self, machine_pool_updates: dict[str, list[dict[str, Any]]]) -> None:
        self.machine_pool_updates: dict[str, list[dict[str, Any]]] = (
            machine_pool_updates
        )

        super().__init__()

        self.labels = []

    @property
    def title(self) -> str:
        return f"[{self.name}] machine pool updates"

    @property
    def description(self) -> str:
        return DecisionCommand.APPROVED.value

    def normalized_machine_pool_updates(self) -> dict[str, list[dict[str, Any]]]:
        return {
            cluster_path: [
                clean_none_values_from_dict(update) for update in pool_updates
            ]
            for cluster_path, pool_updates in self.machine_pool_updates.items()
        }

    def process(self, gitlab_cli: GitLabApi) -> None:
        yaml = create_ruamel_instance(explicit_start=True, width=4096)
        changes = False
        for (
            cluster_path,
            machine_pool_updates,
        ) in self.normalized_machine_pool_updates().items():
            cluster_fs_path = f"data{cluster_path}"
            if not machine_pool_updates:
                continue

            raw_file = gitlab_cli.project.files.get(
                file_path=cluster_fs_path, ref=gitlab_cli.main_branch
            )
            content = yaml.load(raw_file.decode())
            if "machinePools" not in content:
                self.cancel(f"{cluster_fs_path} misses machinePools. Nothing to do.")

            for machine_pool in machine_pool_updates:
                for mp in content["machinePools"]:
                    if mp["id"] == machine_pool["id"]:
                        mp.update(machine_pool)
                        changes = True

            with StringIO() as stream:
                yaml.dump(content, stream)
                new_content = stream.getvalue()

            msg = f"update cluster {cluster_fs_path} machine-pool fields"
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=cluster_fs_path,
                commit_message=msg,
                content=new_content,
            )

        if not changes:
            self.cancel("Clusters are up to date. Nothing to do.")


def clean_none_values_from_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
