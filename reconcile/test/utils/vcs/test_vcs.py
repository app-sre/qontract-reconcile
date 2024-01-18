from collections.abc import Callable, Mapping
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.utils.vcs import VCS, MRCheckStatus


# https://docs.gitlab.com/ee/api/pipelines.html
@pytest.mark.parametrize(
    "pipelines, expected_status",
    [
        ([{"status": "success"}], MRCheckStatus.SUCCESS),
        ([{"status": "failed"}], MRCheckStatus.FAILED),
        ([{"status": "canceled"}], MRCheckStatus.NONE),
        ([], MRCheckStatus.NONE),
    ],
)
def test_gitlab_mr_check_status(
    vcs_builder: Callable[[Mapping], VCS],
    pipelines: list[Mapping],
    expected_status: MRCheckStatus,
) -> None:
    vcs = vcs_builder({
        "MR_PIPELINES": pipelines,
    })

    mr = create_autospec(spec=ProjectMergeRequest)
    assert vcs.get_gitlab_mr_check_status(mr=mr) == expected_status
