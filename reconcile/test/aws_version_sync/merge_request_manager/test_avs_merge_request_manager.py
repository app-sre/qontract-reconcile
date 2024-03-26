from collections.abc import (
    Callable,
    Iterable,
)
from unittest.mock import (
    ANY,
    MagicMock,
    create_autospec,
)

import pytest
from gitlab.v4.objects import ProjectMergeRequest
from pytest_mock import MockerFixture

from reconcile.aws_version_sync.merge_request_manager.merge_request import (
    AVS_LABEL,
    AVSInfo,
    Renderer,
)
from reconcile.aws_version_sync.merge_request_manager.merge_request_manager import (
    AVSMR,
    MergeRequestManager,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.merge_request_manager import OpenMergeRequest
from reconcile.utils.merge_request_manager.parser import (
    Parser,
)
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS


def test_avsmr(mocker: MockerFixture) -> None:
    gitlab_api_mock = mocker.MagicMock(spec=GitLabApi)
    avsmr = AVSMR(
        title="title",
        description="description",
        path="/path",
        content="content",
        labels=["label"],
    )
    assert avsmr.title == "title"
    assert avsmr.description == "description"
    avsmr.process(gitlab_api_mock)
    gitlab_api_mock.update_file.assert_called_once_with(
        branch_name=avsmr.branch,
        file_path="data/path",
        commit_message="aws version sync",
        content="content",
    )


def mr_builder(
    description: str = "",
    labels: Iterable[str] = [AVS_LABEL],
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
    renderer_mock.render_merge_request_content.return_value = "new-content"
    renderer_mock.render_description.return_value = "render_description"
    renderer_mock.render_title.return_value = "title"
    vcs_mock.get_file_content_from_app_interface_master.return_value = (
        "namespace-file-content"
    )

    mrm.create_avs_merge_request(
        namespace_file="namespace_file",
        provider="provider",
        provisioner_ref="provisioner_ref",
        provisioner_uid="provisioner_uid",
        resource_provider="resource_provider",
        resource_identifier="resource_identifier",
        resource_engine="resource_engine",
        resource_engine_version="42.1",
    )

    renderer_mock.render_merge_request_content.assert_called_once_with(
        current_content="namespace-file-content",
        provider="provider",
        provisioner_ref="provisioner_ref",
        resource_provider="resource_provider",
        resource_identifier="resource_identifier",
        resource_engine_version="42.1",
    )
    renderer_mock.render_title.assert_called()
    vcs_mock.open_app_interface_merge_request.assert_called_once()


def test_merge_request_manager_create_avs_merge_request_close_outdated_mr_first(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    raw_mr = mr_builder()
    mrm, vcs_mock, _, _ = mrm_builder()

    mrm._open_mrs = [
        OpenMergeRequest(
            raw=raw_mr,
            mr_info=AVSInfo(
                provider="provider",
                account_id="account_id",
                resource_provider="resource_provider",
                resource_identifier="resource_identifier",
                resource_engine="resource_engine",
                resource_engine_version="42.0",
            ),
        )
    ]

    mrm.create_avs_merge_request(
        namespace_file="namespace_file",
        provider="provider",
        provisioner_ref="provisioner_ref",
        provisioner_uid="account_id",
        resource_provider="resource_provider",
        resource_identifier="resource_identifier",
        resource_engine="resource_engine",
        resource_engine_version="42.1",
    )

    vcs_mock.close_app_interface_mr.assert_called_once_with(raw_mr, ANY)
    vcs_mock.open_app_interface_merge_request.assert_not_called()


def test_merge_request_manager_create_avs_merge_request(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    mrm, vcs_mock, _, _ = mrm_builder()

    mrm.create_avs_merge_request(
        namespace_file="namespace_file",
        provider="provider",
        provisioner_ref="provisioner_ref",
        provisioner_uid="account_id",
        resource_provider="resource_provider",
        resource_identifier="resource_identifier",
        resource_engine="resource_engine",
        resource_engine_version="42.1",
    )

    vcs_mock.close_app_interface_mr.assert_not_called()
    vcs_mock.open_app_interface_merge_request.assert_called_once()


def test_merge_request_manager_create_avs_merge_request_auto_merge_on(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    mrm, vcs_mock, _, _ = mrm_builder()
    mrm._auto_merge_enabled = True

    mrm.create_avs_merge_request(
        namespace_file="namespace_file",
        provider="provider",
        provisioner_ref="provisioner_ref",
        provisioner_uid="account_id",
        resource_provider="resource_provider",
        resource_identifier="resource_identifier",
        resource_engine="resource_engine",
        resource_engine_version="42.1",
    )

    vcs_mock.close_app_interface_mr.assert_not_called()
    _, kwargs = vcs_mock.open_app_interface_merge_request.call_args
    assert kwargs["mr"].labels == [AVS_LABEL, AUTO_MERGE]


def test_merge_request_manager_create_avs_merge_request_auto_merge_off(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock, MagicMock],
    ],
) -> None:
    mrm, vcs_mock, _, _ = mrm_builder()
    mrm._auto_merge_enabled = False

    mrm.create_avs_merge_request(
        namespace_file="namespace_file",
        provider="provider",
        provisioner_ref="provisioner_ref",
        provisioner_uid="account_id",
        resource_provider="resource_provider",
        resource_identifier="resource_identifier",
        resource_engine="resource_engine",
        resource_engine_version="42.1",
    )

    vcs_mock.close_app_interface_mr.assert_not_called()
    assert vcs_mock.open_app_interface_merge_request.call_args.kwargs["mr"].labels == [
        AVS_LABEL
    ]
