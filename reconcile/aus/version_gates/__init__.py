from typing import Type

import semver

from reconcile.aus.version_gates import ocp_gate_handler, sts_version_gate_handler
from reconcile.aus.version_gates.handler import GateHandler
from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.semver_helper import get_version_prefix

HANDLERS: dict[str, Type[GateHandler]] = {
    ocp_gate_handler.GATE_LABEL: ocp_gate_handler.OCPGateHandler,
    sts_version_gate_handler.GATE_LABEL: sts_version_gate_handler.STSGateHandler,
}


def is_gate_applicable_to_cluster(gate: OCMVersionGate, cluster: OCMCluster) -> bool:
    # check that the cluster has an upgrade path that crosses the gate version
    minor_version_upgrade_paths = {
        get_version_prefix(version) for version in cluster.available_upgrades()
    }
    if gate.version_raw_id_prefix not in minor_version_upgrade_paths:
        return False

    # consider only gates after the clusters current minor version
    # OCM onls supports creating gate agreements for later minor versions than the
    # current cluster version
    if not semver.match(
        f"{cluster.minor_version()}.0", f"<{gate.version_raw_id_prefix}.0"
    ):
        return False

    # check the handler for the gate type if it is responsible for this kind
    # of cluster
    handler = HANDLERS.get(gate.label)
    if handler:
        return handler.responsible_for(cluster)
    return False
