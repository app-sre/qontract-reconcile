from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.templating.lib.merge_request_manager import (
    MergeRequestManager,
    TemplateInfo,
    TemplateRenderingMR,
    create_parser,
    render_description,
)
from reconcile.templating.lib.model import TemplateInput, TemplateOutput
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.merge_request_manager import OpenMergeRequest
from reconcile.utils.vcs import VCS


@pytest.fixture
def gitlab_cli(mocker: MockerFixture) -> GitLabApi:
    return mocker.MagicMock(GitLabApi)


@pytest.fixture
def mergereqeustmanager(mocker: MockerFixture) -> tuple[MergeRequestManager, Mock]:
    vcs = mocker.MagicMock(VCS)
    return MergeRequestManager(vcs, create_parser()), vcs


def test_parser_parse() -> None:
    collection = "foo bar"
    shasum = "e8460885f1031d12f4853a4fe0ebf9680c7d82ff21e2159fd89a3983f853203f"

    t = create_parser().parse(render_description(collection, shasum))
    assert isinstance(t, TemplateInfo)
    assert t.collection == collection
    assert t.collection_hash == shasum


@pytest.mark.parametrize("is_new,create,update", [(True, 1, 0), (False, 0, 1)])
def test_templaterenderingmr_process_updated(
    is_new: bool, create: int, update: int, gitlab_cli: Mock
) -> None:
    trm = TemplateRenderingMR(
        "title",
        "description",
        [TemplateOutput(is_new=is_new, content="", path="")],
        ["label"],
    )
    trm.process(gitlab_cli)

    assert gitlab_cli.create_file.call_count == create
    assert gitlab_cli.update_file.call_count == update


def test_create_tr_merge_request_fail(
    mergereqeustmanager: tuple[MergeRequestManager, Mock],
) -> None:
    with pytest.raises(AssertionError):
        mergereqeustmanager[0].create_tr_merge_request(
            [TemplateOutput(is_new=True, content="", path="")],
        )


def test_create_tr_merge_request_create(
    mergereqeustmanager: tuple[MergeRequestManager, Mock],
) -> None:
    mrm, vcs = mergereqeustmanager
    mrm.create_tr_merge_request(
        [
            TemplateOutput(
                input=TemplateInput(collection="foo", collection_hash="abc"),
                is_new=True,
                content="",
                path="",
            )
        ],
    )

    vcs.open_app_interface_merge_request.assert_called_once()


@pytest.mark.parametrize("thash,closed", [("cba", True), ("abc", False)])
def test_create_tr_merge_request_found(
    thash: str,
    closed: bool,
    mergereqeustmanager: tuple[MergeRequestManager, Mock],
    mocker: MockerFixture,
) -> None:
    mrm, vcs = mergereqeustmanager
    mrm._open_mrs.append(
        OpenMergeRequest(
            raw=mocker.patch("gitlab.v4.objects.ProjectMergeRequest", autospec=True),
            mr_info=TemplateInfo(collection="foo", collection_hash=thash),
        )
    )
    mrm.create_tr_merge_request(
        [
            TemplateOutput(
                input=TemplateInput(collection="foo", collection_hash="abc"),
                is_new=True,
                content="",
                path="",
            )
        ],
    )
    if closed:
        vcs.close_app_interface_mr.assert_called_once()
        vcs.open_app_interface_merge_request.assert_called_once()
    else:
        vcs.close_app_interface_mr.assert_not_called()
        vcs.open_app_interface_merge_request.assert_not_called()
