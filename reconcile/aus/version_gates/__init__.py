from typing import Type

from reconcile.aus.version_gates import ocp_gate_handler, sts_version_gate_handler
from reconcile.aus.version_gates.handler import GateHandler

HANDLERS: dict[str, Type[GateHandler]] = {
    ocp_gate_handler.GATE_LABEL: ocp_gate_handler.OCPGateHandler,
    sts_version_gate_handler.GATE_LABEL: sts_version_gate_handler.STSGateHandler,
}
