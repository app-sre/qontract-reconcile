import logging

from pydantic import BaseModel

from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.ocm_machine_pools.integration import AbstractPool
from reconcile.ocm_machine_pools.machine_pools_updates import (
    LABEL,
    CreateMachinePoolsUpdate,
    Parser,
    Renderer,
)
from reconcile.utils.merge_request_manager.merge_request_manager import (
    MergeRequestManagerBase,
)
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS


class MrData(BaseModel):
    machine_pools: list[AbstractPool]
    cluster: ClusterV1


class MachinePoolsUpdateMR(MergeRequestManagerBase):
    """Manager for machine pools update merge requests
    This class is responsible for housekeeping (closing old/bad MRs) and
    opening new MRs.
    """

    def __init__(
        self, vcs: VCS, renderer: Renderer, parser: Parser, auto_merge_enabled: bool
    ):
        super().__init__(vcs, parser, LABEL)
        self._renderer = renderer
        self._auto_merge_enabled = auto_merge_enabled

    def create_merge_request(self, data: MrData) -> None:
        """Opens a new MR, if not already present, for a machine pool modification of a cluster"""

        if not self._housekeeping_ran:
            self.housekeeping()

        cluster = data.cluster
        if self._merge_request_already_exists({"cluster": cluster}):
            logging.info("MR already exists for %s machine pool update", cluster)
            return None

        description = self._renderer.render_description(cluster=cluster.name)
        title = self._renderer.render_title(cluster=cluster.name)
        logging.info("Opening MR for %s machine pools update", cluster)
        mr_labels = [LABEL]
        if self._auto_merge_enabled:
            mr_labels.append(AUTO_MERGE)
        self._vcs.open_app_interface_merge_request(
            mr=CreateMachinePoolsUpdate(
                title=title,
                description=description,
                labels=mr_labels,
                machine_pools_updates=data.machine_pools,
                cluster=cluster,
            )
        )
