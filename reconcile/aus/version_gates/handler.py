from typing import Protocol

from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient


class GateHandler(Protocol):
    """
    A protocol for version gate handlers.
    """

    def responsible_for(self, cluster: OCMCluster) -> bool:
        """
        Check if the handler is responsible for the given cluster.
        """
        ...

    def handle(
        self,
        ocm_api: OCMBaseClient,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        """
        Take all necessary actions required by a version gate.
        If successful, return True. Otherwise, return False.
        """
        ...


class NoopGateHandler:
    """
    A generic handler for version gates. It feels responsible for all clusters
    and does not do anything when handling a version gate.

    This is useful when a version gate does not require any action to be taken
    and the gate is just a wave-through.
    """

    def responsible_for(self, _: OCMCluster) -> bool:
        return True

    def handle(
        self,
        ocm_api: OCMBaseClient,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        return True
