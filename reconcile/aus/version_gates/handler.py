from abc import ABC, abstractmethod

from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient


class GateHandler(ABC):
    """
    A protocol for version gate handlers.
    """

    @staticmethod
    @abstractmethod
    def gate_applicable_to_cluster(cluster: OCMCluster) -> bool:
        """
        Check if the gate represented by this handler is applicable for the given cluster.
        """
        ...

    @abstractmethod
    def handle(
        self,
        ocm_api: OCMBaseClient,
        ocm_org_id: str,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        """
        Take all necessary actions required by a version gate.
        If successful, return True. Otherwise, return False.
        """
        ...
