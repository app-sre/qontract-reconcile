from copy import deepcopy
from typing import Any
from unittest.mock import Mock

from reconcile.aus import cluster_version_data as cvd


def get_data(
    version_data_dict: dict[str, Any], version: str, workload: str
) -> dict[str, Any]:
    return version_data_dict["versions"][version]["workloads"][workload]


def test_version_data_load(state: Mock, ocm1_state: dict[str, Any]) -> None:
    version_data = cvd.get_version_data(state, "prod/org-1-id")
    assert version_data.jsondict() == ocm1_state


def test_version_data_save(state: Mock, ocm1_state: dict[str, Any]) -> None:
    version_data = cvd.get_version_data(state, "prod/org-1-id")
    version_data.save(state, "prod/org-1-id")
    state.add.assert_called_once_with("prod/org-1-id", ocm1_state, force=True)


def test_version_data_old_style_check_in(
    state: Mock, ocm1_state: dict[str, Any]
) -> None:
    # the check_in datetime used to not be using the iso format
    # let's check we can load the old format and still save the new one..
    # this test can be removed once deployed in production since the check_in
    # format will then become the standard ISO
    new_ocm1_state = deepcopy(ocm1_state)
    ocm1_state["check_in"] = "2021-08-29 18:00:00"
    version_data = cvd.get_version_data(state, "prod/org-1-id")
    assert version_data.jsondict() == new_ocm1_state
    version_data.save(state, "prod/org-1-id")
    state.add.assert_called_once_with("prod/org-1-id", new_ocm1_state, force=True)


def test_version_data_load_update_save(
    state: Mock, ocm1_state: dict[str, Any], low_version: str
) -> None:
    version_data = cvd.get_version_data(state, "prod/org-1-id")
    new_ocm1_state = deepcopy(ocm1_state)
    get_data(new_ocm1_state, low_version, "workload1")["soak_days"] = 100.0
    version_data.versions[low_version].workloads["workload1"].soak_days = 100.0
    version_data.save(state, "prod/org-1-id")
    state.add.assert_called_once_with("prod/org-1-id", new_ocm1_state, force=True)


def test_version_data_workload_history(
    state: Mock, ocm1_state: dict[str, Any], low_version: str
) -> None:
    default_wh = cvd.WorkloadHistory()
    version_data = cvd.get_version_data(state, "prod/org-1-id")

    wh = version_data.workload_history(low_version, "workload1")
    assert wh == get_data(ocm1_state, low_version, "workload1")

    wh = version_data.workload_history(low_version, "workload1", default_wh)
    assert wh == get_data(ocm1_state, low_version, "workload1")

    wh = version_data.workload_history(low_version, "does-not-exist")
    assert wh == default_wh

    default_wh.soak_days = 5.0
    wh = version_data.workload_history(low_version, "does-not-exist", default_wh)
    assert wh == default_wh
    # ensure our new default has been set
    wh = version_data.workload_history(low_version, "does-not-exist")
    assert wh == default_wh


def test_version_data_aggregate(
    state: Mock,
    ocm1_state: dict[str, Any],
    ocm2_state: dict[str, Any],
    low_version: str,
    high_version: str,
) -> None:
    version_data = cvd.get_version_data(state, "prod/org-1-id")
    version_data_ocm2 = cvd.get_version_data(state, "prod/org-2-id")
    version_data.aggregate(version_data_ocm2, "prod/org-2-id")

    assert set(version_data.versions.keys()) == {low_version, high_version}

    v1_workloads = version_data.versions[low_version].workloads
    # unkwown workloads are not aggregated
    assert "workload3" not in v1_workloads
    # nothing to aggregate
    assert v1_workloads["workload2"] == get_data(ocm1_state, low_version, "workload2")
    # aggregation of LOW_VERSION/workload1
    ocm1_v1_w1 = get_data(ocm1_state, low_version, "workload1")
    ocm2_v1_w1 = get_data(ocm2_state, low_version, "workload1")
    assert v1_workloads["workload1"] == {
        "soak_days": ocm1_v1_w1["soak_days"] + ocm2_v1_w1["soak_days"],
        "reporting": ocm1_v1_w1["reporting"]
        + [f"prod/org-2-id/{r}" for r in ocm2_v1_w1["reporting"]],
    }

    v2_workloads = version_data.versions[high_version].workloads
    aggregated = get_data(ocm2_state, high_version, "workload1")
    aggregated["reporting"] = [f"prod/org-2-id/{r}" for r in aggregated["reporting"]]
    # new version HIGH_VERSION for workload1 aggregated
    assert v2_workloads == {"workload1": aggregated}

    assert version_data.stats is not None
    assert version_data.stats.inherited == version_data_ocm2.stats


def test_update_stats() -> None:
    pass


def test_validate_against_inherited() -> None:
    pass
