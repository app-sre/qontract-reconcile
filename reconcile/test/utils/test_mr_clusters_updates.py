from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import Project
from qontract_utils.ruamel import dump_yaml

import reconcile.utils.mr.clusters_updates as sut
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import CancelMergeRequestError

fxt = Fixtures("clusters")


@pytest.fixture
def raw_clusters() -> bytes:
    return fxt.get("cluster1.yml").encode()


def test_no_changes() -> None:
    cli = create_autospec(GitLabApi)
    c = sut.CreateClustersUpdates({})
    c.branch = "abranch"

    with pytest.raises(CancelMergeRequestError):
        c.process(cli)

    cli.get_raw_file.assert_not_called()


def test_changes_to_spec(raw_clusters: bytes) -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = raw_clusters
    c = sut.CreateClustersUpdates({
        "cluster1": {"spec": {"id": "42"}, "root": {}, "path": "/a/path"}
    })
    c.branch = "abranch"
    c.process(cli)

    expected = sut.yaml.load(raw_clusters)
    expected["spec"]["id"] = "42"

    cli.update_file.assert_called_once_with(
        branch_name="abranch",
        file_path="/a/path",
        commit_message="update cluster cluster1 spec fields",
        content=dump_yaml(sut.yaml, expected),
    )
    cli.get_raw_file.assert_called_once_with(
        project=cli.project,
        path="/a/path",
        ref=cli.main_branch,
    )


def test_changes_to_root(raw_clusters: bytes) -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = raw_clusters
    c = sut.CreateClustersUpdates({
        "cluster1": {
            "spec": {},
            "root": {"prometheusUrl": "aprometheusurl"},
            "path": "/a/path",
        }
    })
    c.branch = "abranch"
    c.process(cli)

    expected = sut.yaml.load(raw_clusters)
    expected["prometheusUrl"] = "aprometheusurl"

    cli.update_file.assert_called_once_with(
        branch_name="abranch",
        file_path="/a/path",
        commit_message="update cluster cluster1 spec fields",
        content=dump_yaml(sut.yaml, expected),
    )
    cli.get_raw_file.assert_called_once_with(
        project=cli.project,
        path="/a/path",
        ref=cli.main_branch,
    )
