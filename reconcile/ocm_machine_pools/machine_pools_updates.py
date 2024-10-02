from ruamel.yaml import YAML

from reconcile.change_owners.decision import DecisionCommand
from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.ocm_machine_pools.integration import AbstractPool
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase

yaml = YAML()
yaml.explicit_start = True
# Lets prevent line wraps
yaml.width = 4096


class CreateMachinePoolsUpdate(MergeRequestBase):
    name = "create_machine_pools_updates_mr"

    def __init__(
        self,
        machine_pools_updates: list[AbstractPool],
        cluster: ClusterV1,
    ):
        self.machine_pools_updates = machine_pools_updates
        self.cluster = cluster

        super().__init__()

        self.labels = []

    @property
    def title(self) -> str:
        return f"[{self.name}] machine pools updates"

    @property
    def description(self) -> str:
        return DecisionCommand.APPROVED.value

    def process(self, gitlab_cli: GitLabApi) -> None:
        changes = False
        for updates in self.machine_pools_updates:
            if not updates:
                continue

            cluster_path = self.cluster.path
            raw_file = gitlab_cli.project.files.get(
                file_path=cluster_path, ref=gitlab_cli.main_branch
            )

            content = yaml.load(raw_file.decode())
            if "machinePools" not in content:
                self.cancel("Machine Pools not defined. Nothing to update.")

        if not changes:
            self.cancel("Machine pools are up to date. Nothing to do.")
