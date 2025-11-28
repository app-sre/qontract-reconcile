from reconcile.aus.version_gates.handler import GateHandler
from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient

GATE_LABEL = "api.openshift.com/gate-sts"


class STSGateHandler(GateHandler):
    """
    This handler is used to handle the STS version gate.
    Right now we just ack all gate-sts gates
    The actual job of role upgrade is now a part of AUS and is handled by the AUSSTSGateHandler.
    """

    @staticmethod
    def gate_applicable_to_cluster(cluster: OCMCluster) -> bool:
        """
        The STS Gate is applicable to all clusters with STS enabled.
        This could potentially also be OSD STS clusters. While this handler
        does not handle OSD clusters as of now, it is still important that
        we report the STS gate to be applicable to OSD STS clusters.
        """
        return cluster.is_sts()

    def handle(
        self,
        ocm_api: OCMBaseClient,
        ocm_org_id: str,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        return True
