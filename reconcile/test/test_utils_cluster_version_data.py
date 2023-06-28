from copy import deepcopy
from typing import Any
from unittest.mock import Mock

import pytest

from reconcile.utils import cluster_version_data as cvd

LOW_VERSION = "4.12.1"
HIGH_VERSION = "4.12.2"


@pytest.fixture
def ocm1_state():
    return {
        "check_in": "2021-08-29T18:00:00",
        "versions": {
            LOW_VERSION: {
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
            "min_version": LOW_VERSION,
            "min_version_per_workload": {
                "workload1": LOW_VERSION,
            },
        },
    }


@pytest.fixture
def ocm2_state():
    return {
        "check_in": "2021-08-29T18:00:00",
        "versions": {
            LOW_VERSION: {
                "workloads": {
                    "workload1": {
                        "soak_days": 3.0,
                        "reporting": ["cluster4", "cluster5"],
                    },
                    "workload3": {"soak_days": 10.0, "reporting": ["cluster6"]},
                }
            },
            HIGH_VERSION: {
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
            "min_version": LOW_VERSION,
            "min_version_per_workload": {
                "workload1": LOW_VERSION,
                "workload3": HIGH_VERSION,
            },
        },
    }


def get_data(
    version_data_dict: dict[str, Any], version: str, workload: str
) -> dict[str, Any]:
    return version_data_dict["versions"][version]["workloads"][workload]


@pytest.fixture
def state(mocker: Mock, ocm1_state, ocm2_state):
    s = mocker.patch(
        "reconcile.utils.cluster_version_data.State", autospec=True
    ).return_value
    data = {"ocm1": ocm1_state, "ocm2": ocm2_state}
    s.get.side_effect = data.get
    return s


def test_version_data_load(state, ocm1_state):
    version_data = cvd.get_version_data(state, "ocm1")
    assert version_data.jsondict() == ocm1_state


def test_version_data_save(state, ocm1_state):
    version_data = cvd.get_version_data(state, "ocm1")
    version_data.save(state, "ocm1")
    state.add.assert_called_once_with("ocm1", ocm1_state, force=True)


def test_version_data_old_style_check_in(state, ocm1_state):
    # the check_in datetime used to not be using the iso format
    # let's check we can load the old format and still save the new one..
    # this test can be removed once deployed in production since the check_in
    # format will then become the standard ISO
    new_ocm1_state = deepcopy(ocm1_state)
    ocm1_state["check_in"] = "2021-08-29 18:00:00"
    version_data = cvd.get_version_data(state, "ocm1")
    assert version_data.jsondict() == new_ocm1_state
    version_data.save(state, "ocm1")
    state.add.assert_called_once_with("ocm1", new_ocm1_state, force=True)


def test_version_data_load_update_save(state, ocm1_state):
    version_data = cvd.get_version_data(state, "ocm1")
    new_ocm1_state = deepcopy(ocm1_state)
    get_data(new_ocm1_state, LOW_VERSION, "workload1")["soak_days"] = 100.0
    version_data.versions[LOW_VERSION].workloads["workload1"].soak_days = 100.0
    version_data.save(state, "ocm1")
    state.add.assert_called_once_with("ocm1", new_ocm1_state, force=True)


def test_version_data_workload_history(state, ocm1_state):
    default_wh = cvd.WorkloadHistory()
    version_data = cvd.get_version_data(state, "ocm1")

    wh = version_data.workload_history(LOW_VERSION, "workload1")
    assert wh == get_data(ocm1_state, LOW_VERSION, "workload1")

    wh = version_data.workload_history(LOW_VERSION, "workload1", default_wh)
    assert wh == get_data(ocm1_state, LOW_VERSION, "workload1")

    wh = version_data.workload_history(LOW_VERSION, "does-not-exist")
    assert wh == default_wh

    default_wh.soak_days = 5.0
    wh = version_data.workload_history(LOW_VERSION, "does-not-exist", default_wh)
    assert wh == default_wh
    # ensure our new default has been set
    wh = version_data.workload_history(LOW_VERSION, "does-not-exist")
    assert wh == default_wh


def test_version_data_aggregate(state, ocm1_state, ocm2_state):
    version_data = cvd.get_version_data(state, "ocm1")
    version_data_ocm2 = cvd.get_version_data(state, "ocm2")
    version_data.aggregate(version_data_ocm2, "ocm2")

    assert set(version_data.versions.keys()) == {LOW_VERSION, HIGH_VERSION}

    v1_workloads = version_data.versions[LOW_VERSION].workloads
    # unkwown workloads are not aggregated
    assert "workload3" not in v1_workloads
    # nothing to aggregate
    assert v1_workloads["workload2"] == get_data(ocm1_state, LOW_VERSION, "workload2")
    # aggregation of LOW_VERSION/workload1
    ocm1_v1_w1 = get_data(ocm1_state, LOW_VERSION, "workload1")
    ocm2_v1_w1 = get_data(ocm2_state, LOW_VERSION, "workload1")
    assert v1_workloads["workload1"] == {
        "soak_days": ocm1_v1_w1["soak_days"] + ocm2_v1_w1["soak_days"],
        "reporting": ocm1_v1_w1["reporting"]
        + [f"ocm2/{r}" for r in ocm2_v1_w1["reporting"]],
    }

    v2_workloads = version_data.versions[HIGH_VERSION].workloads
    aggregated = get_data(ocm2_state, HIGH_VERSION, "workload1")
    aggregated["reporting"] = [f"ocm2/{r}" for r in aggregated["reporting"]]
    # new version HIGH_VERSION for workload1 aggregated
    assert v2_workloads == {"workload1": aggregated}

    assert version_data.stats is not None
    assert version_data.stats.inherited == version_data_ocm2.stats


def test_update_stats():
    pass


def test_validate_against_inherited():
    pass
