from datetime import datetime
from unittest.mock import MagicMock

import yaml
from pytest_mock import MockerFixture

from reconcile.dashdotdb_dora import (
    AppEnv,
    Commit,
    DashdotdbDORA,
    Deployment,
    RepoChanges,
    SaasTarget,
)


def test_get_repo_ref_for_sha(mocker: MockerFixture):
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)

    # mock gl_app_interface_get_file
    d.gl_app_interface_get_file = MagicMock(
        return_value=yaml.safe_dump({
            "resourceTemplates": [
                {
                    "name": "rt0",
                    "url": "url0",
                    "ref": "ref0",
                    "targets": [
                        {"namespace": {"$ref": "ns0"}, "ref": "ref0"},
                        {"namespace": {"$ref": "ns3"}, "ref": "ref3"},
                    ],
                },
                {
                    "name": "rt1",
                    "url": "url1",
                    "ref": "ref1",
                    "targets": [
                        {"namespace": {"$ref": "ns0"}, "ref": "ref0"},
                        {"namespace": {"$ref": "ns1"}, "ref": "ref1"},
                    ],
                },
            ]
        }).encode("utf-8")
    )

    saastarget = SaasTarget("app1", "env1", "/path1", "rt1", "ns1", "pipeline1")
    info = d.get_repo_ref_for_sha(saastarget, "sha")

    assert info == ("url1", "ref1")


def test_get_repo_ref_for_sha_none(mocker: MockerFixture):
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)

    # mock gl_app_interface_get_file
    d.gl_app_interface_get_file = MagicMock(
        return_value=yaml.safe_dump({
            "resourceTemplates": [
                {
                    "name": "rt10",
                    "url": "url0",
                    "ref": "ref0",
                    "targets": [
                        {"namespace": {"$ref": "ns0"}, "ref": "ref0"},
                        {"namespace": {"$ref": "ns3"}, "ref": "ref3"},
                    ],
                },
                {
                    "name": "rt11",
                    "url": "url1",
                    "ref": "ref1",
                    "targets": [
                        {"namespace": {"$ref": "ns0"}, "ref": "ref0"},
                        {"namespace": {"$ref": "ns1"}, "ref": "ref1"},
                    ],
                },
            ]
        }).encode("utf-8")
    )

    saastarget = SaasTarget("app1", "env1", "/path1", "rt1", "ns1", "pipeline1")
    info = d.get_repo_ref_for_sha(saastarget, "sha")

    assert info == (None, None)


def test_compare_gh(mocker: MockerFixture):
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)
    ghapi_mock = MagicMock()

    def gl_commit_mock(sha, date):
        obj = MagicMock()
        obj.sha = sha
        obj.commit.committer.date = date
        return obj

    ghapi_mock.compare.return_value = [
        gl_commit_mock(
            "8cfb8408f614e1d0179d75af793f3fddf42d054a", datetime(2023, 9, 1, 0, 0, 0)
        ),
        gl_commit_mock(
            "81677e1bc71324c9fa5c747b494add5a5af5e653", datetime(2023, 9, 2, 0, 0, 0)
        ),
        gl_commit_mock(
            "566f37f8e9985d775e619cc959b806f5a254a380", datetime(2023, 9, 3, 0, 0, 0)
        ),
        gl_commit_mock(
            "adab91701311fec1b0f5405adddaf68f886bba2c", datetime(2023, 9, 4, 0, 0, 0)
        ),
    ]

    d._gh_apis = {"my/repo": ghapi_mock}

    repo = "https://github.com/my/repo"

    repo_changes = RepoChanges(
        repo,
        "e000dafd2e7bf34be41e7b3a5cb529ce7fbde257",
        "adab91701311fec1b0f5405adddaf68f886bba2c",
    )
    rc, commits = d.compare(repo_changes)
    assert rc == repo_changes
    assert commits == [
        Commit(
            repo,
            "8cfb8408f614e1d0179d75af793f3fddf42d054a",
            datetime(2023, 9, 1, 0, 0, 0),
        ),
        Commit(
            repo,
            "81677e1bc71324c9fa5c747b494add5a5af5e653",
            datetime(2023, 9, 2, 0, 0, 0),
        ),
        Commit(
            repo,
            "566f37f8e9985d775e619cc959b806f5a254a380",
            datetime(2023, 9, 3, 0, 0, 0),
        ),
        Commit(
            repo,
            "adab91701311fec1b0f5405adddaf68f886bba2c",
            datetime(2023, 9, 4, 0, 0, 0),
        ),
    ]


def test_compare_gl(mocker: MockerFixture):
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)
    d.gl = MagicMock()
    d.gl.server = "https://gitlab.com"
    d.gl.repository_compare.return_value = [
        {
            "id": "8cfb8408f614e1d0179d75af793f3fddf42d054a",
            "committed_date": "2023-09-01T00:00:00",
        },
        {
            "id": "81677e1bc71324c9fa5c747b494add5a5af5e653",
            "committed_date": "2023-09-02T00:00:00",
        },
        {
            "id": "566f37f8e9985d775e619cc959b806f5a254a380",
            "committed_date": "2023-09-03T00:00:00",
        },
        {
            "id": "adab91701311fec1b0f5405adddaf68f886bba2c",
            "committed_date": "2023-09-04T00:00:00",
        },
    ]
    repo = "https://gitlab.com/my/repo"

    repo_changes = RepoChanges(
        repo,
        "e000dafd2e7bf34be41e7b3a5cb529ce7fbde257",
        "adab91701311fec1b0f5405adddaf68f886bba2c",
    )
    rc, commits = d.compare(repo_changes)
    assert rc == repo_changes
    assert commits == [
        Commit(
            repo,
            "8cfb8408f614e1d0179d75af793f3fddf42d054a",
            datetime(2023, 9, 1, 0, 0, 0),
        ),
        Commit(
            repo,
            "81677e1bc71324c9fa5c747b494add5a5af5e653",
            datetime(2023, 9, 2, 0, 0, 0),
        ),
        Commit(
            repo,
            "566f37f8e9985d775e619cc959b806f5a254a380",
            datetime(2023, 9, 3, 0, 0, 0),
        ),
        Commit(
            repo,
            "adab91701311fec1b0f5405adddaf68f886bba2c",
            datetime(2023, 9, 4, 0, 0, 0),
        ),
    ]


def test_get_latest_with_default(mocker: MockerFixture):
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)
    d.dashdotdb_url = "http://localhost"

    date = datetime(2023, 9, 3, 0, 0, 0)
    appenv = AppEnv("app1", "env1")

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"finish_timestamp": date.isoformat()}

    d._do_get = MagicMock(return_value=response)  # type: ignore[method-assign]

    latest = d.get_latest_with_default(date, appenv)
    assert latest == (
        AppEnv(app_name="app1", env_name="env1"),
        datetime(2023, 9, 3, 0, 0),
    )


def test_get_repo_changes(mocker: MockerFixture):
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)

    saastarget = SaasTarget("app1", "env1", "/path1", "rt1", "ns1", "pipeline1")
    date = datetime(2023, 9, 3, 0, 0)
    deployment = Deployment("trigger1", date)
    saastarget_deployment = (saastarget, deployment)

    d.get_repo_ref_for_sha = MagicMock(  # type: ignore[method-assign]
        side_effect=[("repo1", "commitA"), ("repo1", "commitB")]
    )

    exp_saas_target, exp_deployment, repo_changes = d.get_repo_changes(
        saastarget_deployment
    )
    assert exp_saas_target == saastarget
    assert exp_deployment == deployment
    assert repo_changes == RepoChanges("repo1", "commitA", "commitB")
