import re
import string

from pydantic import BaseModel
from ruamel.yaml import YAML

from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.ocm_machine_pools.integration import AbstractPool
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.mr.base import MergeRequestBase

yaml = YAML()
yaml.explicit_start = True
# Lets prevent line wraps
yaml.width = 4096

PROMOTION_DATA_SEPARATOR = "**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
VERSION = "0.1.0"
LABEL = "machine-pools-updates"

VERSION_REF = "machine_pools"
CLUSTER_REF = "cluster"
COMPILED_REGEXES = {
    i: re.compile(rf".*{i}: (.*)$", re.MULTILINE) for i in [VERSION_REF, CLUSTER_REF]
}

DESC = string.Template(
    f"""
This MR is triggered by app-interface's [ocm-machine-pools](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/ocm_machine_pools).

Please **do not remove** the **{LABEL}** label from this MR!

Parts of this description are used by integration to manage the MR.

{PROMOTION_DATA_SEPARATOR}

* {VERSION_REF}: {VERSION}
* {CLUSTER_REF}: $cluster
"""
)


class Info(BaseModel):
    account: str


def create_parser() -> Parser:
    """Create a parser for MRs created by ocm-machine-pools."""

    return Parser[Info](
        klass=Info,
        compiled_regexes=COMPILED_REGEXES,
        version_ref=VERSION_REF,
        expected_version=VERSION,
        data_separator=PROMOTION_DATA_SEPARATOR,
    )


class Renderer:
    """This class is only concerned with rendering text for MRs."""

    def render_description(self, cluster: str) -> str:
        return DESC.safe_substitute(cluster=cluster)

    def render_title(self, cluster: str) -> str:
        return f"[auto] OCM machine-pools update to {cluster}"


class CreateMachinePoolsUpdate(MergeRequestBase):
    name = "create_machine_pools_updates_mr"

    def __init__(
        self,
        title: str,
        description: str,
        labels: list[str],
        machine_pools_updates: list[AbstractPool],
        cluster: ClusterV1,
    ):
        super().__init__()
        self._title = title
        self._description = description
        self.machine_pools_updates = machine_pools_updates
        self.cluster = cluster
        self.labels = labels

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

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
