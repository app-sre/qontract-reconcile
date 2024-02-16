from collections.abc import Callable
from typing import Any

import pytest

from reconcile.aus import base
from reconcile.test.ocm.fixtures import (
    OcmUrl,
    build_ocm_cluster,
)
from reconcile.utils.ocm.clusters import OCMCluster
from reconcile.utils.ocm.upgrades import OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def version_gate_4_13_ocp_id() -> str:
    return "f0bbef99-d1ea-11ed-aefd-0a580a800209"


@pytest.fixture
def version_gate_4_13_ocp(version_gate_4_13_ocp_id: str) -> dict[str, Any]:
    return {
        "kind": "VersionGate",
        "id": version_gate_4_13_ocp_id,
        "version_raw_id_prefix": "4.13",
        "label": "api.openshift.com/gate-ocp",
        "value": "4.13",
        "sts_only": False,
    }


@pytest.fixture
def version_gate_4_13_sts_id() -> str:
    return "ec6fa2a0-d1ea-11ed-aefd-0a580a800209"


@pytest.fixture
def version_gate_4_13_sts(version_gate_4_13_sts_id: str) -> dict[str, Any]:
    return {
        "kind": "VersionGate",
        "id": version_gate_4_13_sts_id,
        "version_raw_id_prefix": "4.13",
        "label": "api.openshift.com/gate-sts",
        "value": "4.13",
        "sts_only": True,
    }


@pytest.fixture
def version_gates(
    version_gate_4_13_ocp: dict[str, Any], version_gate_4_13_sts: dict[str, Any]
) -> list[dict[str, Any]]:
    # this fixture is used to mock the response from the OCM API
    return [version_gate_4_13_ocp, version_gate_4_13_sts]


@pytest.fixture
def cluster_version_gate_agreement_4_13_ocp(
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    cluster: OCMCluster,
    version_gate_4_13_ocp: dict[str, Any],
) -> str:
    gate_agreement_id = "cluster-1-4-13-ocp"
    register_ocm_url_responses([
        OcmUrl(
            method="GET",
            uri=f"/api/clusters_mgmt/v1/clusters/{cluster.id}/gate_agreements",
        ).add_list_response([
            {
                "kind": "VersionGateAgreement",
                "id": gate_agreement_id,
                "href": f"/api/clusters_mgmt/v1/clusters/{cluster.id}/gate_agreements/{gate_agreement_id}",
                "version_gate": version_gate_4_13_ocp,
            }
        ])
    ])
    return gate_agreement_id


@pytest.fixture
def cluster_version_gate_agreement_4_13_sts(
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    cluster: OCMCluster,
    version_gate_4_13_sts: dict[str, Any],
) -> str:
    gate_agreement_id = "cluster-1-4-13-sts"
    register_ocm_url_responses([
        OcmUrl(
            method="GET",
            uri=f"/api/clusters_mgmt/v1/clusters/{cluster.id}/gate_agreements",
        ).add_list_response([
            {
                "kind": "VersionGateAgreement",
                "id": gate_agreement_id,
                "href": f"/api/clusters_mgmt/v1/clusters/{cluster.id}/gate_agreements/{gate_agreement_id}",
                "version_gate": version_gate_4_13_sts,
            }
        ])
    ])
    return gate_agreement_id


@pytest.fixture
def cluster_version_gate_agreement_none(
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    cluster: OCMCluster,
    version_gate_4_13_sts: dict[str, Any],
) -> str:
    gate_agreement_id = "cluster-1-4-13-sts"
    register_ocm_url_responses([
        OcmUrl(
            method="GET",
            uri=f"/api/clusters_mgmt/v1/clusters/{cluster.id}/gate_agreements",
        ).add_list_response([])
    ])
    return gate_agreement_id


@pytest.fixture
def cluster() -> OCMCluster:
    return build_ocm_cluster(
        name="cluster",
        version="4.12.17",
        available_upgrades=["4.12.19"],
    )


#
# test gate agreement
#


def test_gates_to_agree_no_minor_upgrade(
    cluster: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_ocp_id: str,
    cluster_version_gate_agreement_none: str,
    ocm_api: OCMBaseClient,
) -> None:
    gates = base.gates_to_agree(
        gates=base.gates_for_minor_version(
            [OCMVersionGate(**g) for g in version_gates], "4.12"
        ),
        cluster=cluster,
        ocm_api=ocm_api,
    )
    assert gates == []


def test_gates_to_agree_ignore_old_version_gates(
    cluster: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_ocp_id: str,
    cluster_version_gate_agreement_none: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster.version.raw_id = "4.13.1"
    cluster.version.available_upgrades = ["4.13.2"]
    gates = base.gates_to_agree(
        gates=base.gates_for_minor_version(
            [OCMVersionGate(**g) for g in version_gates], "4.13"
        ),
        cluster=cluster,
        ocm_api=ocm_api,
    )
    assert gates == []


def test_gates_to_agree_ocp_agreement_required(
    cluster: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_ocp_id: str,
    cluster_version_gate_agreement_none: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster.version.available_upgrades = ["4.13.2"]
    cluster.aws.sts.enabled = False  # type: ignore
    gates = base.gates_to_agree(
        gates=base.gates_for_minor_version(
            [OCMVersionGate(**g) for g in version_gates], "4.13"
        ),
        cluster=cluster,
        ocm_api=ocm_api,
    )
    assert {g.id for g in gates} == {version_gate_4_13_ocp_id}


def test_gates_to_agree_ocp_agreement_present(
    cluster: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_ocp_id: str,
    cluster_version_gate_agreement_4_13_ocp: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster.version.available_upgrades = ["4.13.2"]
    cluster.aws.sts.enabled = False  # type: ignore
    gates = base.gates_to_agree(
        gates=base.gates_for_minor_version(
            [OCMVersionGate(**g) for g in version_gates], "4.13"
        ),
        cluster=cluster,
        ocm_api=ocm_api,
    )
    assert gates == []


def test_gates_to_agree_sts_cluster_agreement_required(
    cluster: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_sts_id: str,
    version_gate_4_13_ocp_id: str,
    cluster_version_gate_agreement_none: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster.version.available_upgrades = ["4.13.2"]
    cluster.aws.sts.enabled = True  # type: ignore
    gates = base.gates_to_agree(
        gates=base.gates_for_minor_version(
            [OCMVersionGate(**g) for g in version_gates], "4.13"
        ),
        cluster=cluster,
        ocm_api=ocm_api,
    )
    # version gate for sts is not present becaues we don't want to agree to them automatically for now
    assert {g.id for g in gates} == {version_gate_4_13_ocp_id}


def test_gates_to_agree_sts_agreement_present(
    cluster: OCMCluster,
    version_gates: list[dict[str, Any]],
    version_gate_4_13_sts_id: str,
    version_gate_4_13_ocp_id: str,
    cluster_version_gate_agreement_4_13_sts: str,
    ocm_api: OCMBaseClient,
) -> None:
    cluster.version.available_upgrades = ["4.13.2"]
    cluster.aws.sts.enabled = True  # type: ignore
    gates = base.gates_to_agree(
        gates=base.gates_for_minor_version(
            [OCMVersionGate(**g) for g in version_gates], "4.13"
        ),
        cluster=cluster,
        ocm_api=ocm_api,
    )
    assert {g.id for g in gates} == {version_gate_4_13_ocp_id}
