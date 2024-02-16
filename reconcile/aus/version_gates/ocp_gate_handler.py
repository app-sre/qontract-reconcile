from reconcile.aus.version_gates.handler import GateHandler
from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient

GATE_LABEL = "api.openshift.com/gate-ocp"


class OCPGateHandler(GateHandler):
    """
    Right now we just ack all gate-ocp gates...
    We could do better in the future, e.g. inspecting insights findings on the cluster
    """

    @staticmethod
    def responsible_for(_: OCMCluster) -> bool:
        return True

    def handle(
        self,
        ocm_api: OCMBaseClient,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        return True
