from collections.abc import Callable, Iterable
from unittest.mock import MagicMock, create_autospec

import pytest
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest
from pytest_mock import MockerFixture

from reconcile.terraform_vpc_resources.merge_request import LABEL, Info, Renderer
from reconcile.terraform_vpc_resources.merge_request_manager import (
    MergeRequestManager,
    MrData,
    VPCRequestMR,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.vcs import VCS


def test_vpc_request_mr_creates_file_when_is_update_false(
    mocker: MockerFixture,
) -> None:
    """Test VPCRequestMR.process() creates file when is_update=False."""
    gitlab_api_mock = mocker.MagicMock(spec=GitLabApi)

    mr = VPCRequestMR(
        title="title",
        description="description",
        vpc_tmpl_file_path="/path/to/file.yml",
        vpc_tmpl_file_content="new content",
        labels=["label"],
        is_update=False,
    )

    mr.process(gitlab_api_mock)

    # Should create file
    gitlab_api_mock.create_file.assert_called_once_with(
        branch_name=mr.branch,
        file_path="/path/to/file.yml",
        commit_message="add vpc datafile",
        content="new content",
    )
    # Should NOT call update_file
    gitlab_api_mock.update_file.assert_not_called()


def test_vpc_request_mr_updates_file_when_is_update_true(
    mocker: MockerFixture,
) -> None:
    """Test VPCRequestMR.process() updates file when is_update=True."""
    gitlab_api_mock = mocker.MagicMock(spec=GitLabApi)

    mr = VPCRequestMR(
        title="title",
        description="description",
        vpc_tmpl_file_path="/path/to/file.yml",
        vpc_tmpl_file_content="new content",
        labels=["label"],
        is_update=True,
    )

    mr.process(gitlab_api_mock)

    # Should update file
    gitlab_api_mock.update_file.assert_called_once_with(
        branch_name=mr.branch,
        file_path="/path/to/file.yml",
        commit_message="update vpc datafile",
        content="new content",
    )
    # Should NOT call create_file
    gitlab_api_mock.create_file.assert_not_called()


def mr_builder(
    description: str = "",
    labels: Iterable[str] = [LABEL],
    has_conflicts: bool = False,
) -> ProjectMergeRequest:
    """Build a mock ProjectMergeRequest for testing."""
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
    """Build a MergeRequestManager with mocked dependencies."""

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


def test_merge_request_manager_creates_mr_when_file_does_not_exist(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    """Test MergeRequestManager creates MR when file doesn't exist (404)."""
    mrm, vcs_mock, renderer_mock, _ = mrm_builder()
    # File does not exist in the repo
    vcs_mock.get_file_content_from_app_interface_ref.side_effect = GitlabGetError(
        response_code=404
    )

    renderer_mock.render_title.return_value = "[auto] VPC data file creation to account"
    renderer_mock.render_description.return_value = "MR description"

    mrm.create_merge_request(MrData(account="account", content="content", path="/path"))

    # Should use create title, not update title
    renderer_mock.render_title.assert_called_once_with(account="account")
    renderer_mock.render_update_title.assert_not_called()
    renderer_mock.render_description.assert_called_once_with(account="account")

    # Should open MR with is_update=False
    vcs_mock.open_app_interface_merge_request.assert_called_once()
    call_args = vcs_mock.open_app_interface_merge_request.call_args
    mr = call_args.kwargs["mr"]
    assert isinstance(mr, VPCRequestMR)
    assert mr._is_update is False


def test_merge_request_manager_creates_mr_when_file_exists_with_different_content(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    """Test MergeRequestManager creates MR when file exists but content differs."""
    mrm, vcs_mock, renderer_mock, _ = mrm_builder()
    # File exists with different content
    vcs_mock.get_file_content_from_app_interface_ref.return_value = "old content"

    renderer_mock.render_update_title.return_value = (
        "[auto] VPC data file update for account"
    )
    renderer_mock.render_description.return_value = "MR description"

    mrm.create_merge_request(
        MrData(account="account", content="new content", path="/path")
    )

    # Should use update title, not create title
    renderer_mock.render_update_title.assert_called_once_with(account="account")
    renderer_mock.render_title.assert_not_called()
    renderer_mock.render_description.assert_called_once_with(account="account")

    # Should open MR with is_update=True
    vcs_mock.open_app_interface_merge_request.assert_called_once()
    call_args = vcs_mock.open_app_interface_merge_request.call_args
    mr = call_args.kwargs["mr"]
    assert isinstance(mr, VPCRequestMR)
    assert mr._is_update is True


def test_merge_request_manager_skips_mr_when_file_exists_with_same_content(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    """Test MergeRequestManager skips MR creation when file exists with same content."""
    mrm, vcs_mock, renderer_mock, _ = mrm_builder()
    # File exists with same content (including whitespace handling)
    vcs_mock.get_file_content_from_app_interface_ref.return_value = "  content  \n"

    mrm.create_merge_request(
        MrData(account="account", content="  content  ", path="/path")
    )

    # Should NOT create MR
    vcs_mock.open_app_interface_merge_request.assert_not_called()
    # Should NOT call renderers
    renderer_mock.render_title.assert_not_called()
    renderer_mock.render_update_title.assert_not_called()
    renderer_mock.render_description.assert_not_called()


def test_merge_request_manager_skips_mr_when_already_exists(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    """Test MergeRequestManager skips MR creation when one already exists."""
    # Create MR manager with existing open MR
    description = """
**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**

* tf_vpc_resources_version: 0.1.0
* account: account
"""
    open_mrs = [mr_builder(description=description)]
    mrm, vcs_mock, _, parser_mock = mrm_builder(open_mrs=open_mrs)

    parser_mock.parse.return_value = Info(account="account")

    mrm.create_merge_request(MrData(account="account", content="content", path="/path"))

    # Should NOT check file content
    vcs_mock.get_file_content_from_app_interface_ref.assert_not_called()
    # Should NOT create MR
    vcs_mock.open_app_interface_merge_request.assert_not_called()


def test_merge_request_manager_reraises_non_404_errors(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    """Test MergeRequestManager re-raises non-404 GitlabGetError."""
    mrm, vcs_mock, _, _ = mrm_builder()
    # Simulate a different error (e.g., 500 Internal Server Error)
    vcs_mock.get_file_content_from_app_interface_ref.side_effect = GitlabGetError(
        response_code=500
    )

    # Should re-raise the error
    with pytest.raises(GitlabGetError) as exc_info:
        mrm.create_merge_request(
            MrData(account="account", content="content", path="/path")
        )

    assert exc_info.value.response_code == 500
    # Should NOT create MR
    vcs_mock.open_app_interface_merge_request.assert_not_called()


def test_renderer_create_title() -> None:
    """Test Renderer.render_title() generates correct create title."""
    renderer = Renderer()
    title = renderer.render_title(account="test-account")
    assert title == "[auto] VPC data file creation to test-account"


def test_renderer_update_title() -> None:
    """Test Renderer.render_update_title() generates correct update title."""
    renderer = Renderer()
    title = renderer.render_update_title(account="test-account")
    assert title == "[auto] VPC data file update for test-account"


def test_renderer_description() -> None:
    """Test Renderer.render_description() generates correct description."""
    renderer = Renderer()
    description = renderer.render_description(account="test-account")
    assert "test-account" in description
    assert "terraform-vpc-resources" in description
    assert "**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**" in description
