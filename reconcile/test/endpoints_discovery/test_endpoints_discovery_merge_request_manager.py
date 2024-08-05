from collections.abc import Callable, Iterable
from random import shuffle
from unittest.mock import ANY, MagicMock, create_autospec

import pytest
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest
from pytest_mock import MockerFixture

from reconcile.endpoints_discovery.merge_request import (
    LABEL,
    Renderer,
    create_parser,
)
from reconcile.endpoints_discovery.merge_request_manager import (
    App,
    Endpoint,
    EndpointsDiscoveryMR,
    MergeRequestManager,
    hash_apps,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS


@pytest.fixture()
def app() -> App:
    return App(
        name="app-1",
        path="/path/app-1.yml",
        endpoints_to_add=[
            Endpoint(
                name="endpoint-to-add-1",
                data={
                    "name": "endpoint-to-add-1",
                    "url": "https://fake-route.com:80",
                },
            ),
            Endpoint(
                name="endpoint-to-add-2",
                data={
                    "name": "endpoint-to-add-2",
                    "url": "https://fake-route.com:80",
                },
            ),
        ],
        endpoints_to_change=[
            Endpoint(
                name="endpoint-to-change-1",
                data={
                    "name": "endpoint-to-change-1",
                    "url": "https://fake-route.com:80",
                },
            ),
            Endpoint(
                name="endpoint-to-change-2",
                data={
                    "name": "endpoint-to-change-2",
                    "url": "https://fake-route.com:80",
                },
            ),
        ],
        endpoints_to_delete=[
            Endpoint(
                name="endpoint-to-delete-1",
            ),
            Endpoint(
                name="endpoint-to-delete-2",
            ),
        ],
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
    [Iterable[ProjectMergeRequest]], tuple[MergeRequestManager, VCS, Renderer]
]:
    def builder(
        open_mrs: Iterable[ProjectMergeRequest] | None = None,
    ) -> tuple[MergeRequestManager, VCS, Renderer]:
        vcs_mock = mocker.create_autospec(spec=VCS)
        if open_mrs:
            vcs_mock.get_open_app_interface_merge_requests.side_effect = [open_mrs]
        renderer_mock = mocker.MagicMock(spec=Renderer)

        return (
            MergeRequestManager(
                vcs=vcs_mock,
                renderer=renderer_mock,
                parser=create_parser(),
                auto_merge_enabled=True,
            ),
            vcs_mock,
            renderer_mock,
        )

    return builder


def test_endpoints_discovery_merge_request_manager_mr(mocker: MockerFixture) -> None:
    gitlab_api_mock = mocker.MagicMock(spec=GitLabApi)
    mr = EndpointsDiscoveryMR(
        title="title",
        description="description",
        labels=["label"],
    )
    assert mr.title == "title"
    assert mr.description == "description"
    mr.add_commit(path="/path", content="content", msg="msg")
    mr.process(gitlab_api_mock)
    gitlab_api_mock.update_file.assert_called_once_with(
        branch_name=mr.branch,
        file_path="/path",
        commit_message="msg",
        content="content",
    )


def test_endpoints_discovery_merge_request_manager_hash_apps() -> None:
    apps = [
        App(name="app-1", path="/path/app-1.yml"),
        App(name="app-2", path="/path/app-2.yml"),
        App(name="app-3", path="/path/app-3.yml"),
    ]
    # shuffle to ensure the hash is always the same
    shuffle(apps)
    assert (
        hash_apps(apps)
        == "289bc5c0644b5d297bd9546f778736fd25165177795dc5fdbe5421d6430b660d"
    )


def test_endpoints_discovery_merge_request_manager_app(app: App) -> None:
    # shuffle to ensure the hash is always the same
    shuffle(app.endpoints_to_add)
    shuffle(app.endpoints_to_change)
    shuffle(app.endpoints_to_delete)
    assert (
        app.hash == "8b09ab363499304987686af3bbed5157ecb9fea164e334969e6ef85494f88f0e"
    )


def test_endpoints_discovery_merge_request_manager_create_merge_request_mr_already_created_and_up2date(
    mrm_builder: Callable[
        [list[ProjectMergeRequest]],
        tuple[MergeRequestManager, MagicMock, MagicMock],
    ],
    app: App,
) -> None:
    mr = mr_builder(description=Renderer().render_description(hash=hash_apps([app])))
    mrm, vcs_mock, _ = mrm_builder([mr])

    mrm.create_merge_request(apps=[app])

    # nothing called
    vcs_mock.close_app_interface_mr.assert_not_called()
    vcs_mock.open_app_interface_merge_request.assert_not_called()


def test_endpoints_discovery_merge_request_manager_create_merge_request_mr_already_created_but_outdated(
    mrm_builder: Callable[
        [list[ProjectMergeRequest]],
        tuple[MergeRequestManager, MagicMock, MagicMock],
    ],
    app: App,
) -> None:
    mr = mr_builder(description=Renderer().render_description(hash="some-other-hash"))
    mrm, vcs_mock, _ = mrm_builder([mr])

    mrm.create_merge_request(apps=[app])

    vcs_mock.close_app_interface_mr.assert_called_once()
    # nothing else called
    vcs_mock.open_app_interface_merge_request.assert_not_called()


def test_endpoints_discovery_merge_request_manager_create_merge_request_app_file_missing(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock],
    ],
    app: App,
) -> None:
    mrm, vcs_mock, _ = mrm_builder()
    # file does not exist in the repo
    vcs_mock.get_file_content_from_app_interface_master.side_effect = GitlabGetError(
        response_code=404
    )

    mrm.create_merge_request(apps=[app])

    vcs_mock.close_app_interface_mr.assert_not_called()
    vcs_mock.open_app_interface_merge_request.assert_not_called()


def test_endpoints_discovery_merge_request_manager_create_merge_request_open_mr(
    mrm_builder: Callable[
        [],
        tuple[MergeRequestManager, MagicMock, MagicMock],
    ],
    app: App,
) -> None:
    mrm, vcs_mock, render_mock = mrm_builder()
    render_mock.render_title.return_value = "title"
    render_mock.render_description.return_value = "description"
    render_mock.render_merge_request_content.return_value = "content"
    vcs_mock.get_file_content_from_app_interface_master.return_value = "content"

    mrm.create_merge_request(apps=[app])
    vcs_mock.open_app_interface_merge_request.assert_called_once_with(ANY)
    mr_arg = vcs_mock.open_app_interface_merge_request.call_args.kwargs["mr"]
    assert isinstance(mr_arg, EndpointsDiscoveryMR)
    assert mr_arg.title == "title"
    assert mr_arg.description == "description"
    assert mr_arg.labels == [LABEL, AUTO_MERGE]
    assert len(mr_arg._commits) == 1
    commit = mr_arg._commits[0]
    assert commit[0] == "data/path/app-1.yml"
    assert commit[1] == "content"
    assert commit[2]
