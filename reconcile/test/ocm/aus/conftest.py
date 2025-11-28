from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.aus.cluster_version_data import VersionData
from reconcile.aus.version_gates import ocp_gate_handler
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.ocm.base import OCMVersionGate


@pytest.fixture
def ocm_env() -> OCMEnvironment:
    return OCMEnvironment(
        name="env",
        description="env desc",
        labels="{}",
        url="https://ocm",
        accessTokenUrl="https://sso/token",
        accessTokenClientId="client-id",
        accessTokenClientSecret=VaultSecret(
            field="client-secret", path="path", format=None, version=None
        ),
    )


@pytest.fixture
def low_version() -> str:
    return "4.12.1"


@pytest.fixture
def high_version() -> str:
    return "4.12.2"


@pytest.fixture
def state(
    mocker: MockerFixture, ocm1_state: dict[str, Any], ocm2_state: dict[str, Any]
) -> Mock:
    s = mocker.patch("reconcile.utils.state.State", autospec=True).return_value
    data = {"prod/org-1-id": ocm1_state, "prod/org-2-id": ocm2_state}
    s.get.side_effect = data.get
    return s


@pytest.fixture
def ocm1_state(low_version: str) -> dict[str, Any]:
    return {
        "check_in": "2021-08-29T18:00:00",
        "versions": {
            low_version: {
                "workloads": {
                    "workload1": {
                        "soak_days": 21.0,
                        "reporting": ["cluster1", "cluster2"],
                    },
                    "workload2": {"soak_days": 6.0, "reporting": ["cluster3"]},
                }
            }
        },
        "stats": {
            "min_version": low_version,
            "min_version_per_workload": {
                "workload1": low_version,
            },
        },
    }


@pytest.fixture
def ocm1_version_data(ocm1_state: dict[str, Any]) -> VersionData:
    return VersionData(**ocm1_state)


@pytest.fixture
def ocm2_state(low_version: str, high_version: str) -> dict[str, Any]:
    return {
        "check_in": "2021-08-29T18:00:00",
        "versions": {
            low_version: {
                "workloads": {
                    "workload1": {
                        "soak_days": 3.0,
                        "reporting": ["cluster4", "cluster5"],
                    },
                    "workload3": {"soak_days": 10.0, "reporting": ["cluster6"]},
                }
            },
            high_version: {
                "workloads": {
                    "workload1": {
                        "soak_days": 13.0,
                        "reporting": ["cluster4", "cluster5"],
                    },
                    "workload3": {"soak_days": 20.0, "reporting": ["cluster6"]},
                }
            },
        },
        "stats": {
            "min_version": low_version,
            "min_version_per_workload": {
                "workload1": low_version,
                "workload3": high_version,
            },
        },
    }


@pytest.fixture
def ocm2_version_data(ocm2_state: dict[str, Any]) -> VersionData:
    return VersionData(**ocm2_state)


VERSION_GATE_4_12_OCP_ID = "e3ed7585-7033-11ed-ac97-0a580a830014"
VERSION_GATE_4_13_OCP_ID = "f0bbef99-d1ea-11ed-aefd-0a580a800209"
VERSION_GATE_4_13_STS_ID = "ec6fa2a0-d1ea-11ed-aefd-0a580a800209"


@pytest.fixture
def version_gate_4_12_ocp() -> OCMVersionGate:
    return OCMVersionGate(**{
        "kind": "VersionGate",
        "id": VERSION_GATE_4_12_OCP_ID,
        "version_raw_id_prefix": "4.12",
        "label": ocp_gate_handler.GATE_LABEL,
        "value": "4.12",
        "sts_only": False,
    })


@pytest.fixture
def version_gate_4_13_ocp() -> OCMVersionGate:
    return OCMVersionGate(**{
        "kind": "VersionGate",
        "id": VERSION_GATE_4_13_OCP_ID,
        "version_raw_id_prefix": "4.13",
        "label": ocp_gate_handler.GATE_LABEL,
        "value": "4.13",
        "sts_only": False,
    })


@pytest.fixture
def version_gates(version_gate_4_13_ocp: OCMVersionGate) -> list[OCMVersionGate]:
    return [version_gate_4_13_ocp]
