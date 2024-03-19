from reconcile.aus.version_gates.handler import GateHandler
from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient

GATE_LABEL = "api.openshift.com/gate-ingress"


class IngressGateHandler(GateHandler):
    """
    https://access.redhat.com/node/7028653
    """

    @staticmethod
    def gate_applicable_to_cluster(_: OCMCluster) -> bool:
        # applicable to all cluster types
        return True

    def handle(
        self,
        ocm_api: OCMBaseClient,
        ocm_org_id: str,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        # there is no automatic remediation for this gate
        # users need to manually do the required changes to their clusters
        # or their clusters are not affected and they can accept the gate
        # in the upgradePolicy.versionGateApprovals field
        return True
