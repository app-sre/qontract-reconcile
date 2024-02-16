import pytest
from pytest_mock import MockerFixture

from reconcile.aus import version_gate_approver
from reconcile.aus.base import gates_to_agree
from reconcile.aus.version_gate_approver import (
    VersionGateApprover,
    VersionGateApproverParams,
)
from reconcile.aus.version_gates.handler import GateHandler
from reconcile.aus.version_gates.sts_version_gate_handler import STSGateHandler
from reconcile.test.ocm.aus.fixtures import NoopGateHandler
from reconcile.test.ocm.fixtures import build_ocm_cluster
from reconcile.utils.ocm.base import (
    PRODUCT_ID_OSD,
    PRODUCT_ID_ROSA,
    OCMCluster,
    OCMVersionGate,
)
from reconcile.utils.ocm_base_client import OCMBaseClient

VERSION_GATE_4_13_OCP_ID = "f0bbef99-d1ea-11ed-aefd-0a580a800209"
VERSION_GATE_4_13_STS_ID = "ec6fa2a0-d1ea-11ed-aefd-0a580a800209"

GATE_LABEL_STS = "api.openshift.com/gate-sts"
GATE_LABEL_OCP = "api.openshift.com/gate-ocp"


@pytest.fixture
def version_gate_4_13_ocp() -> OCMVersionGate:
    return OCMVersionGate(**{
        "kind": "VersionGate",
        "id": VERSION_GATE_4_13_OCP_ID,
        "version_raw_id_prefix": "4.13",
        "label": "api.openshift.com/gate-ocp",
        "value": "4.13",
        "sts_only": False,
    })


@pytest.fixture
def version_gate_4_13_sts() -> OCMVersionGate:
    return OCMVersionGate(**{
        "kind": "VersionGate",
        "id": VERSION_GATE_4_13_STS_ID,
        "version_raw_id_prefix": "4.13",
        "label": "api.openshift.com/gate-sts",
        "value": "4.13",
        "sts_only": True,
    })


@pytest.fixture
def version_gates(
    version_gate_4_13_ocp: OCMVersionGate, version_gate_4_13_sts: OCMVersionGate
) -> list[OCMVersionGate]:
    return [version_gate_4_13_ocp, version_gate_4_13_sts]


@pytest.fixture
def integration() -> VersionGateApprover:
    approver = VersionGateApprover(
        params=VersionGateApproverParams(
            job_controller_cluster="cluster",
            job_controller_namespace="namespace",
        )
    )
    approver.handlers = {
        GATE_LABEL_STS: STSGateHandler(rosa_session_builder={}),
        GATE_LABEL_OCP: NoopGateHandler(),
    }
    return approver


@pytest.mark.parametrize(
    "cluster,acked_version_gate_ids,expected_unacked_version_gate_ids",
    [
        # minor OSD upgrade: OCP gate acked, STS gate not relevant
        (
            build_ocm_cluster(
                "c",
                cluster_product=PRODUCT_ID_OSD,
                version="4.12.17",
                available_upgrades=["4.13.1"],
            ),
            [VERSION_GATE_4_13_OCP_ID],
            [],
        ),
        # minor ROSA non-STS upgrade: OCP gate acked, STS gate not relevant
        (
            build_ocm_cluster(
                "c",
                cluster_product=PRODUCT_ID_ROSA,
                sts_cluster=False,
                version="4.12.17",
                available_upgrades=["4.13.1"],
            ),
            [VERSION_GATE_4_13_OCP_ID],
            [],
        ),
        # minor ROSA STS upgrade: OCP gate acked, STS gate not relevant
        (
            build_ocm_cluster(
                "c",
                cluster_product=PRODUCT_ID_ROSA,
                sts_cluster=True,
                version="4.12.17",
                available_upgrades=["4.13.1"],
            ),
            [VERSION_GATE_4_13_OCP_ID],
            [VERSION_GATE_4_13_STS_ID],
        ),
        # minor ROSA HCP upgrade: OCP gate already acked, STS gate not acked
        (
            build_ocm_cluster(
                "c",
                cluster_product=PRODUCT_ID_ROSA,
                sts_cluster=True,
                hypershift=True,
                version="4.12.17",
                available_upgrades=["4.13.1"],
            ),
            [VERSION_GATE_4_13_OCP_ID],
            [VERSION_GATE_4_13_STS_ID],
        ),
        # minor OSD upgrade: OCP gate not acked, STS gate not relevant
        (
            build_ocm_cluster(
                "c",
                cluster_product=PRODUCT_ID_OSD,
                version="4.12.17",
                available_upgrades=["4.13.1"],
            ),
            [],
            [VERSION_GATE_4_13_OCP_ID],
        ),
        # minor ROSA non-STS upgrade: OCP gate not acked, STS gate not relevant
        (
            build_ocm_cluster(
                "c",
                cluster_product=PRODUCT_ID_ROSA,
                sts_cluster=False,
                version="4.12.17",
                available_upgrades=["4.13.1"],
            ),
            [],
            [VERSION_GATE_4_13_OCP_ID],
        ),
        # minor ROSA STS upgrade: OCP gate not acked, STS gate not acked
        (
            build_ocm_cluster(
                "c",
                cluster_product=PRODUCT_ID_ROSA,
                sts_cluster=True,
                version="4.12.17",
                available_upgrades=["4.13.1"],
            ),
            [],
            [VERSION_GATE_4_13_OCP_ID, VERSION_GATE_4_13_STS_ID],
        ),
        # no upgrades available
        (
            build_ocm_cluster("c", version="4.12.17", available_upgrades=[]),
            [],
            [],
        ),
        # no upgrades to new minor version available
        (
            build_ocm_cluster("c", version="4.12.17", available_upgrades=["4.12.18"]),
            [],
            [],
        ),
    ],
)
def test_get_relevant_gates_for_cluster(
    version_gates: list[OCMVersionGate],
    cluster: OCMCluster,
    acked_version_gate_ids: set[str],
    expected_unacked_version_gate_ids: set[str],
) -> None:
    unacked_gates = gates_to_agree(
        cluster=cluster,
        gates=version_gates,
        acked_gate_ids=acked_version_gate_ids,
    )
    assert [gate.id for gate in unacked_gates] == expected_unacked_version_gate_ids


class MockGateHandler(GateHandler):
    def __init__(self, handle_success: bool) -> None:
        self.handle_success = handle_success

    @staticmethod
    def responsible_for(cluster: OCMCluster) -> bool:
        return True

    def handle(
        self,
        ocm_api: OCMBaseClient,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        return self.handle_success


@pytest.mark.parametrize(
    "gate_handled",
    [
        # the gate was handled, so we expect an agreement creation
        True,
        # the gate was not handled, so we expect no agreement creation
        False,
    ],
)
def test_version_gate_approver_process_cluster(
    integration: VersionGateApprover,
    version_gate_4_13_ocp: OCMVersionGate,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    gate_handled: bool,
) -> None:
    create_version_agreement_mock = mocker.patch.object(
        version_gate_approver, "create_version_agreement"
    )
    cluster = build_ocm_cluster(
        name="rosa-classic-cluster",
        version="4.12.17",
        available_upgrades=["4.13.1"],
    )
    integration.handlers = {version_gate_4_13_ocp.label: MockGateHandler(gate_handled)}
    integration.process_cluster(
        cluster=cluster,
        gates=[version_gate_4_13_ocp],
        ocm_api=ocm_api,
        dry_run=False,
    )

    if gate_handled:
        create_version_agreement_mock.assert_called_once()
    else:
        create_version_agreement_mock.assert_not_called()
