from typing import Any, Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.oc import OCCli


@pytest.fixture
def oc(mocker: MockerFixture) -> OCCli:
    oc = mocker.create_autospec(OCCli)
    oc.get_items.side_effect = [[]]
    return oc


OCItemSetter = Callable[[list[list[dict[str, Any]]]], None]


@pytest.fixture
def set_oc_get_items_side_effect(
    oc: OCCli,
) -> OCItemSetter:
    def _set_oc_get_items_side_effect(
        item_sequence: list[list[dict[str, Any]]],
    ) -> None:
        oc.get_items.side_effect = item_sequence  # type: ignore[attr-defined]

    return _set_oc_get_items_side_effect


@pytest.fixture
def controller(oc: OCCli, mocker: MockerFixture) -> K8sJobController:
    controller = K8sJobController(
        oc=oc,
        cluster="some-cluster",
        namespace="some-ns",
        integration="some-integration",
        integration_version="0.1",
        dry_run=False,
        time_module=TimeMock(),
    )
    mocker.patch.object(controller, "_lookup_job_uid", return_value="some-uid")
    return controller


class TimeMock:
    def __init__(self) -> None:
        self.current_time = 0.0

    def time(self) -> float:
        return self.current_time

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Negative value for sleep seconds not allowed")
        self.current_time += seconds
