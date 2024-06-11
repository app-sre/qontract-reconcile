from reconcile.aus.version_gates import (
    ingress_gate_handler,
    ocp_gate_handler,
    sts_version_gate_handler,
)
from reconcile.aus.version_gates.handler import GateHandler

HANDLERS: dict[str, type[GateHandler]] = {
    ocp_gate_handler.GATE_LABEL: ocp_gate_handler.OCPGateHandler,
    sts_version_gate_handler.GATE_LABEL: sts_version_gate_handler.STSGateHandler,
    ingress_gate_handler.GATE_LABEL: ingress_gate_handler.IngressGateHandler,
}
