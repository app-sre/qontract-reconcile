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
        # and then need to ack the gate on their own or let version-gate-approver
        # do it for them when they list this gate under upgradePolicy.versionGateApprovals
        # in their cluster file or the sre-capabilities.aus.version-gate-approvals
        # OCM subscription label
        return True
