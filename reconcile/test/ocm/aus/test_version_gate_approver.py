from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.aus import version_gate_approver
from reconcile.aus.advanced_upgrade_service import aus_label_key
from reconcile.aus.base import gates_to_agree
from reconcile.aus.version_gate_approver import (
    VersionGateApprover,
    VersionGateApproverParams,
    get_enabled_gate_handlers,
)
from reconcile.aus.version_gates import ocp_gate_handler
from reconcile.aus.version_gates.handler import GateHandler
from reconcile.aus.version_gates.sts_version_gate_handler import STSGateHandler
from reconcile.test.ocm.aus.fixtures import NoopGateHandler
from reconcile.test.ocm.fixtures import build_ocm_cluster
from reconcile.test.ocm.test_utils_ocm_labels import build_subscription_label
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobStatus
from reconcile.utils.ocm.base import (
    PRODUCT_ID_OSD,
    PRODUCT_ID_ROSA,
    OCMCluster,
    OCMLabel,
    OCMVersionGate,
    build_label_container,
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
        "label": GATE_LABEL_OCP,
        "value": "4.13",
        "sts_only": False,
    })


@pytest.fixture
def version_gate_4_13_sts() -> OCMVersionGate:
    return OCMVersionGate(**{
        "kind": "VersionGate",
        "id": VERSION_GATE_4_13_STS_ID,
        "version_raw_id_prefix": "4.13",
        "label": GATE_LABEL_STS,
        "value": "4.13",
        "sts_only": True,
    })


@pytest.fixture
def version_gates(
    version_gate_4_13_ocp: OCMVersionGate, version_gate_4_13_sts: OCMVersionGate
) -> list[OCMVersionGate]:
    return [version_gate_4_13_ocp, version_gate_4_13_sts]


@pytest.fixture
def job_controller() -> K8sJobController:
    jc = MagicMock(
        spec=K8sJobController,
        autospec=True,
    )
    jc.store_job_logs.return_value = None
    jc.enqueue_job_and_wait_for_completion.return_value = JobStatus.SUCCESS
    return jc


@pytest.fixture
def integration(job_controller: K8sJobController) -> VersionGateApprover:
    approver = VersionGateApprover(
        params=VersionGateApproverParams(
            job_controller_cluster="cluster",
            job_controller_namespace="namespace",
            rosa_job_service_account="sa",
            rosa_role="role",
        )
    )
    approver.handlers = {
        GATE_LABEL_STS: STSGateHandler(
            job_controller=job_controller,
            aws_iam_role="role",
        ),
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
    def __init__(self, gate_handler_result: bool, handler_failure: bool) -> None:
        self.gate_handler_result = gate_handler_result
        self.handler_failure = handler_failure

    @staticmethod
    def responsible_for(cluster: OCMCluster) -> bool:
        return True

    def handle(
        self,
        ocm_api: OCMBaseClient,
        ocm_org_id: str,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        if self.handler_failure:
            raise Exception("Handler failure")
        return self.gate_handler_result


@pytest.mark.parametrize(
    "gate_handler_enabled, gate_handler_result, expected_call_count",
    [
        # the gate handler was successful, so we expect an agreement creation
        (True, True, 1),
        # the gate handler was not successful, so we expect no agreement creation
        (True, False, 0),
        # the gate handler was not enabled, so we don't expect a call to the handler
        (False, True, 0),
    ],
)
def test_version_gate_approver_process_cluster(
    integration: VersionGateApprover,
    version_gate_4_13_ocp: OCMVersionGate,
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
    gate_handler_enabled: bool,
    gate_handler_result: bool,
    expected_call_count: int,
) -> None:
    create_version_agreement_mock = mocker.patch.object(
        version_gate_approver, "create_version_agreement"
    )
    cluster = build_ocm_cluster(
        name="rosa-classic-cluster",
        version="4.12.17",
        available_upgrades=["4.13.1"],
    )
    integration.handlers = {
        version_gate_4_13_ocp.label: MockGateHandler(
            gate_handler_result=gate_handler_result,
            handler_failure=not gate_handler_enabled,
        )
    }
    integration.process_cluster(
        cluster=cluster,
        enabled_gate_handlers={version_gate_4_13_ocp.label}
        if gate_handler_enabled
        else set(),
        gates=[version_gate_4_13_ocp],
        ocm_api=ocm_api,
        ocm_org_id="org_id",
        dry_run=False,
    )

    assert create_version_agreement_mock.call_count == expected_call_count


@pytest.mark.parametrize(
    "labels, expected_handlers",
    [
        (
            [
                build_subscription_label(
                    key=aus_label_key("version-gate-approvals"),
                    value="a",
                    subs_id="sub_id",
                )
            ],
            {"a"},
        ),
        (
            [
                build_subscription_label(
                    key=aus_label_key("version-gate-approvals"),
                    value="a,b,c",
                    subs_id="sub_id",
                )
            ],
            {"a", "b", "c"},
        ),
        (
            [
                build_subscription_label(
                    key=aus_label_key("version-gate-approvals"),
                    value="",
                    subs_id="sub_id",
                )
            ],
            {ocp_gate_handler.GATE_LABEL},
        ),
        (
            [
                build_subscription_label(
                    key=aus_label_key("some-other-label"),
                    value="a,b,c",
                    subs_id="sub_id",
                )
            ],
            {ocp_gate_handler.GATE_LABEL},
        ),
        (
            [],
            {ocp_gate_handler.GATE_LABEL},
        ),
    ],
)
def test_get_enabled_gate_handlers(
    labels: list[OCMLabel] | None, expected_handlers: set[str]
) -> None:
    assert get_enabled_gate_handlers(build_label_container(labels)) == expected_handlers
