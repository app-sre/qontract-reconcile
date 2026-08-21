from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import yaml

from reconcile.dashdotdb_dora import (
    AppEnv,
    Commit,
    DashdotdbDORA,
    Deployment,
    RepoChanges,
    SaasTarget,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest
    from pytest_mock import MockerFixture


def test_get_repo_ref_for_sha(mocker: MockerFixture) -> None:
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


def test_get_repo_ref_for_sha_none(mocker: MockerFixture) -> None:
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


def test_compare_gh(mocker: MockerFixture) -> None:
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)
    ghapi_mock = MagicMock()

    def gl_commit_mock(sha: str, date: datetime) -> MagicMock:
        obj = MagicMock()
        obj.sha = sha
        obj.commit.committer.date = date
        return obj

    ghapi_mock.compare.return_value = [
        gl_commit_mock(
            "8cfb8408f614e1d0179d75af793f3fddf42d054a",
            datetime(2023, 9, 1, 0, 0, 0, tzinfo=UTC),
        ),
        gl_commit_mock(
            "81677e1bc71324c9fa5c747b494add5a5af5e653",
            datetime(2023, 9, 2, 0, 0, 0, tzinfo=UTC),
        ),
        gl_commit_mock(
            "566f37f8e9985d775e619cc959b806f5a254a380",
            datetime(2023, 9, 3, 0, 0, 0, tzinfo=UTC),
        ),
        gl_commit_mock(
            "adab91701311fec1b0f5405adddaf68f886bba2c",
            datetime(2023, 9, 4, 0, 0, 0, tzinfo=UTC),
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
            datetime(2023, 9, 1, 0, 0, 0, tzinfo=UTC),
        ),
        Commit(
            repo,
            "81677e1bc71324c9fa5c747b494add5a5af5e653",
            datetime(2023, 9, 2, 0, 0, 0, tzinfo=UTC),
        ),
        Commit(
            repo,
            "566f37f8e9985d775e619cc959b806f5a254a380",
            datetime(2023, 9, 3, 0, 0, 0, tzinfo=UTC),
        ),
        Commit(
            repo,
            "adab91701311fec1b0f5405adddaf68f886bba2c",
            datetime(2023, 9, 4, 0, 0, 0, tzinfo=UTC),
        ),
    ]


def test_compare_gl(mocker: MockerFixture) -> None:
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)
    d.gl = MagicMock()
    d.gl.server = "https://gitlab.com"
    d.gl.repository_compare.return_value = [
        {
            "id": "8cfb8408f614e1d0179d75af793f3fddf42d054a",
            "committed_date": "2023-09-01T00:00:00+00:00",
        },
        {
            "id": "81677e1bc71324c9fa5c747b494add5a5af5e653",
            "committed_date": "2023-09-02T00:00:00+00:00",
        },
        {
            "id": "566f37f8e9985d775e619cc959b806f5a254a380",
            "committed_date": "2023-09-03T00:00:00+00:00",
        },
        {
            "id": "adab91701311fec1b0f5405adddaf68f886bba2c",
            "committed_date": "2023-09-04T00:00:00+00:00",
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
            datetime(2023, 9, 1, 0, 0, 0, tzinfo=UTC),
        ),
        Commit(
            repo,
            "81677e1bc71324c9fa5c747b494add5a5af5e653",
            datetime(2023, 9, 2, 0, 0, 0, tzinfo=UTC),
        ),
        Commit(
            repo,
            "566f37f8e9985d775e619cc959b806f5a254a380",
            datetime(2023, 9, 3, 0, 0, 0, tzinfo=UTC),
        ),
        Commit(
            repo,
            "adab91701311fec1b0f5405adddaf68f886bba2c",
            datetime(2023, 9, 4, 0, 0, 0, tzinfo=UTC),
        ),
    ]


def test_get_latest_with_default(mocker: MockerFixture) -> None:
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)
    d.dashdotdb_url = "http://localhost"

    date = datetime(2023, 9, 3, 0, 0, 0, tzinfo=UTC)
    appenv = AppEnv("app1", "env1")

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"finish_timestamp": date.isoformat()}

    d._do_get = MagicMock(return_value=response)  # type: ignore[method-assign]

    latest = d.get_latest_with_default(date, appenv)
    assert latest == (
        AppEnv(app_name="app1", env_name="env1"),
        datetime(2023, 9, 3, 0, 0, tzinfo=UTC),
    )


def test_get_repo_changes(mocker: MockerFixture) -> None:
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)

    saastarget = SaasTarget("app1", "env1", "/path1", "rt1", "ns1", "pipeline1")
    date = datetime(2023, 9, 3, 0, 0, tzinfo=UTC)
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


def test_post_deployments_skips_when_token_acquisition_fails(
    mocker: MockerFixture,
) -> None:
    from contextlib import contextmanager

    from reconcile.dashdotdb_base import DashdotdbTokenError

    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(False, "1", 1)
    d.dry_run = False
    d.logmarker = "DORA"
    d.scope = "dora"

    @contextmanager
    def _failing_token() -> Iterator[None]:
        raise DashdotdbTokenError("simulated failure")
        yield

    d._token = _failing_token  # type: ignore[method-assign]
    d.post = MagicMock()  # type: ignore[method-assign]

    d._post_deployments([{"some": "deployment"}])

    d.post.assert_not_called()


def test_post_skips_http_in_dry_run(
    mocker: MockerFixture,
) -> None:
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(True, "1", 1)
    d.dry_run = True
    d.dashdotdb_url = "https://dashdotdb.example.com"
    d.dashdotdb_user = "user"
    d.dashdotdb_pass = "pass"
    d.dashdotdb_token = None
    d.logmarker = "DORA"

    d._do_post = MagicMock()  # type: ignore[method-assign]

    d.post({"deployments": []})

    d._do_post.assert_not_called()


def test_post_logs_deployment_count_in_dry_run(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocker.patch("reconcile.dashdotdb_dora.DashdotdbDORA.__init__").return_value = None
    d = DashdotdbDORA(True, "1", 1)
    d.dry_run = True
    d.logmarker = "DORA"

    d._do_post = MagicMock()  # type: ignore[method-assign]

    with caplog.at_level(logging.INFO):
        d.post({"deployments": [{"a": 1}, {"b": 2}]})

    # Dry-run must skip the HTTP call but still report what would be posted, so
    # operators verifying wiring get the same visibility DVO and SLO provide.
    d._do_post.assert_not_called()
    assert "would post 2 deployments" in caplog.text
