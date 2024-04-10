from collections.abc import Callable, Iterable
from unittest.mock import ANY, MagicMock, create_autospec

import pytest
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest
from pytest_mock import MockerFixture

from reconcile.terraform_init.merge_request import LABEL, Renderer
from reconcile.terraform_init.merge_request_manager import (
    MergeRequestManager,
    MrData,
    TerraformInitMR,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.vcs import VCS


def test_terrafom_init_mr(mocker: MockerFixture) -> None:
    gitlab_api_mock = mocker.MagicMock(spec=GitLabApi)
    mr = TerraformInitMR(
        title="title",
        description="description",
        path="/path",
        content="content",
        labels=["label"],
    )
    assert mr.title == "title"
    assert mr.description == "description"
    mr.process(gitlab_api_mock)
    gitlab_api_mock.create_file.assert_called_once_with(
        branch_name=mr.branch,
        file_path="/path",
        commit_message=ANY,
        content="content",
    )


def mr_builder(
    description: str = "",
    labels: Iterable[str] = [LABEL],
    has_conflicts: bool = False,
) -> ProjectMergeRequest:
    mr = create_autospec(spec=ProjectMergeRequest)
    mr.labels = labels
    mr.attributes = {
        "description": description,
        "web_url": "http://localhost",
        "has_conflicts": has_conflicts,
    }
    return mr


@pytest.fixture()
def mrm_builder(
    mocker: MockerFixture,
) -> Callable[
    [Iterable[ProjectMergeRequest]], tuple[MergeRequestManager, VCS, Renderer, Parser]
]:
    def builder(
        open_mrs: Iterable[ProjectMergeRequest] | None = None,
    ) -> tuple[MergeRequestManager, VCS, Renderer, Parser]:
        vcs_mock = mocker.create_autospec(spec=VCS)
        if open_mrs:
            vcs_mock.get_open_app_interface_merge_requests.side_effect = [open_mrs]
        renderer_mock = mocker.MagicMock(spec=Renderer)
        parser_mock = mocker.MagicMock(spec=Parser)
        return (
            MergeRequestManager(
                vcs=vcs_mock,
                renderer=renderer_mock,
                parser=parser_mock,
                auto_merge_enabled=True,
            ),
            vcs_mock,
            renderer_mock,
            parser_mock,
        )

    return builder


def test_merge_request_manager_create_avs_merge_request_renderer_called(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    mrm, vcs_mock, renderer_mock, _ = mrm_builder()
    # file does not exist in the repo
    vcs_mock.get_file_content_from_app_interface_master.side_effect = GitlabGetError(
        response_code=404
    )

    mrm.create_merge_request(MrData(account="account", content="content", path="/path"))

    renderer_mock.render_title.assert_called()
    renderer_mock.render_title.render_description()
    vcs_mock.open_app_interface_merge_request.assert_called_once()


def test_merge_request_manager_create_avs_merge_request_renderer_called_template_collection_already_in_repo(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    mrm, vcs_mock, _, _ = mrm_builder()
    # file does not exist in the repo
    vcs_mock.get_file_content_from_app_interface_master.return_value = "content"

    mrm.create_merge_request(MrData(account="account", content="content", path="/path"))
    vcs_mock.open_app_interface_merge_request.assert_not_called()
