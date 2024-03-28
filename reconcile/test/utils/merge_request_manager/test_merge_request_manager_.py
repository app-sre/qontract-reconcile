from unittest.mock import Mock

import pytest
from gitlab.v4.objects import ProjectMergeRequest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from reconcile.test.utils.merge_request_manager.conftest import desc_string
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.merge_request_manager import (
    MergeRequestManagerBase,
)
from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.vcs import VCS


@pytest.fixture
def gitlab_cli(mocker: MockerFixture) -> GitLabApi:
    return mocker.MagicMock(GitLabApi)


class TestData(BaseModel):
    data_ref1: str


class TestMRManager(MergeRequestManagerBase[TestData]):
    def __init__(self, vcs: VCS, parser: Parser, label: str):
        super().__init__(vcs, parser, label)

    def create_merge_request(self, data: BaseModel) -> None:
        return None


@pytest.fixture
def mergereqeustmanager(
    parser: Parser, mocker: MockerFixture
) -> tuple[TestMRManager, Mock]:
    vcs = mocker.MagicMock(VCS)

    return TestMRManager(vcs, parser, "foo"), vcs


@pytest.mark.parametrize(
    "attributes,closed_reason",
    [
        (
            {
                "description": desc_string.format(
                    version_ref="version_ref", data_ref1="data_ref1"
                ),
                "has_conflicts": False,
            },
            "",
        ),
        (
            {
                "description": "description",
                "has_conflicts": True,
            },
            "Closing this MR because of a merge-conflict.",
        ),
        (
            {
                "description": desc_string.format(
                    version_ref="version_ref", data_ref1="data_ref1"
                ).replace("1.0.0", "2.0.0"),
                "has_conflicts": False,
            },
            "Closing this MR because it has an outdated integration version",
        ),
        (
            {
                "description": "foo-bar",
                "has_conflicts": False,
            },
            "Closing this MR because of bad description format.",
        ),
    ],
)
def test_housekeeping(
    attributes: dict,
    closed_reason: str,
    mergereqeustmanager: tuple[TestMRManager, Mock],
    mocker: MockerFixture,
) -> None:
    mrm, vcs = mergereqeustmanager
    mr = mocker.MagicMock(ProjectMergeRequest)
    mr.labels = ["foo"]
    mr.attributes = attributes
    vcs.get_open_app_interface_merge_requests.return_value = [mr]
    mrm._open_mrs = []
    mrm.housekeeping()
    if closed_reason:
        vcs.close_app_interface_mr.assert_called_with(mr, closed_reason)
    else:
        vcs.close_app_interface_mr.assert_not_called()
        assert len(mrm._open_mrs) == 1
        assert mrm._open_mrs[0].raw == mr
        assert mrm._housekeeping_ran


def test_merge_request_manager_fetch_avs_managed_open_merge_requests(
    mergereqeustmanager: tuple[TestMRManager, Mock],
    mocker: MockerFixture,
) -> None:
    mrm, vcs = mergereqeustmanager
    mr = mocker.MagicMock(ProjectMergeRequest)
    mr.labels = ["foo"]
    vcs.get_open_app_interface_merge_requests.return_value = [mr]

    mrs = mrm._fetch_managed_open_merge_requests()
    assert len(mrs) == 1
    vcs.get_open_app_interface_merge_requests.assert_called_once()
