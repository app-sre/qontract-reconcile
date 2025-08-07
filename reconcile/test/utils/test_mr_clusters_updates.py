from io import StringIO
from unittest import TestCase
from unittest.mock import MagicMock, create_autospec, patch

from gitlab.v4.objects import Project

import reconcile.utils.mr.clusters_updates as sut
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gitlab_api import GitLabApi

fxt = Fixtures("clusters")


@patch.object(sut.CreateClustersUpdates, "cancel")
class TestProcess(TestCase):
    def setUp(self) -> None:
        self.clusters = [fxt.get_anymarkup("cluster1.yml")]
        self.raw_clusters = fxt.get("cluster1.yml")

    def test_no_changes(self, cancel: MagicMock) -> None:
        cli = create_autospec(GitLabApi)
        c = sut.CreateClustersUpdates({})
        c.branch = "abranch"
        c.process(cli)
        cancel.assert_called_once()

        cli.get_raw_file.assert_not_called()

    def test_changes_to_spec(self, cancel: MagicMock) -> None:
        cli = create_autospec(GitLabApi)
        cli.project = create_autospec(Project)
        cli.get_raw_file.return_value = self.raw_clusters.encode()
        c = sut.CreateClustersUpdates({
            "cluster1": {"spec": {"id": "42"}, "root": {}, "path": "/a/path"}
        })
        c.branch = "abranch"
        c.process(cli)
        self.clusters[0]["spec"]["id"] = "42"

        with StringIO() as stream:
            sut.yaml.dump(self.clusters[0], stream)
            content = stream.getvalue()

        cli.update_file.assert_called_once_with(
            branch_name="abranch",
            file_path="/a/path",
            commit_message="update cluster cluster1 spec fields",
            content=content,
        )
        cli.get_raw_file.assert_called_once_with(
            project=cli.project,
            path="/a/path",
            ref=cli.main_branch,
        )
        cancel.assert_not_called()

    def test_changes_to_root(self, cancel: MagicMock) -> None:
        cli = create_autospec(GitLabApi)
        cli.project = create_autospec(Project)
        cli.get_raw_file.return_value = self.raw_clusters.encode()
        c = sut.CreateClustersUpdates({
            "cluster1": {
                "spec": {},
                "root": {"prometheusUrl": "aprometheusurl"},
                "path": "/a/path",
            }
        })
        c.branch = "abranch"
        c.process(cli)
        self.clusters[0]["prometheusUrl"] = "aprometheusurl"

        with StringIO() as stream:
            sut.yaml.dump(self.clusters[0], stream)
            content = stream.getvalue()
        cli.update_file.assert_called_once_with(
            branch_name="abranch",
            file_path="/a/path",
            commit_message="update cluster cluster1 spec fields",
            content=content,
        )
        cli.get_raw_file.assert_called_once_with(
            project=cli.project,
            path="/a/path",
            ref=cli.main_branch,
        )
        cancel.assert_not_called()
