import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.jjb_client import JJB


@pytest.fixture
def github_job_fixture() -> dict[str, Any]:
    return {
        "name": "service-foobar2-build",
        "properties": [{"github": {"url": "http://github.com"}}],
        "triggers": [
            {"github-pull-request": {"trigger-phrase": ".*"}},
        ],
    }


@pytest.fixture
def gitlab_job_fixture() -> dict[str, Any]:
    return {
        "name": "service-foobar-pr-check",
        "properties": [
            {"github": {"url": "http://mygilabinstance.org/service/foobar"}},
        ],
        "triggers": [
            {"gitlab": {"note-regex": "my_trigger_regex.*"}},
        ],
    }


@pytest.fixture
def gitlab_pr_check_job_fixture() -> dict[str, Any]:
    return {
        "name": "service-foobar-pr-check",
        "properties": [
            {"github": {"url": "http://mygilabinstance.org/service/foobar"}},
        ],
        "triggers": [
            {"gitlab": {"trigger-merge-request": True}},
        ],
    }


@pytest.fixture
def gitlab_build_job_fixture() -> dict[str, Any]:
    return {
        "name": "service-foobar-pr-check",
        "properties": [
            {"github": {"url": "http://mygilabinstance.org/service/foobar"}},
        ],
        "triggers": [
            {"gitlab": {"trigger-merge-request": False, "trigger-push": True}},
        ],
    }


@pytest.fixture
def gitlab_test_job_fixture() -> dict[str, Any]:
    return {
        "name": "service-foobar-pr-check",
        "properties": [
            {"github": {"url": "http://mygilabinstance.org/service/foobar"}},
        ],
        "triggers": [
            {
                "gitlab": {
                    "trigger-merge-request": False,
                    "trigger-push": False,
                    "trigger-note": True,
                }
            },
        ],
    }


@pytest.fixture
def patch_jjb(
    mocker: MockerFixture,
    github_job_fixture: dict[str, Any],
    gitlab_job_fixture: dict[str, Any],
) -> Any:
    mocker.patch(
        "reconcile.utils.jjb_client.JJB.__init__", return_value=None, autospec=True
    )
    return mocker.patch(
        "reconcile.utils.jjb_client.JJB.get_all_jobs",
        return_value={"ci": [github_job_fixture, gitlab_job_fixture]},
        autospec=True,
    )


@pytest.fixture
def patch_logging(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.utils.jjb_client.logging")


@pytest.fixture
def patch_et_parse(mocker: MockerFixture) -> MagicMock:
    et = mocker.patch("reconcile.utils.jjb_client.ET")
    et.parse.return_value.getroot.return_value.tag = "job"
    return et


def test_get_job_by_repo_url(
    patch_jjb: Any, gitlab_job_fixture: dict[str, Any]
) -> None:
    jjb = JJB([])
    job = jjb.get_job_by_repo_url(
        "http://mygilabinstance.org/service/foobar", "pr-check"
    )
    assert job["name"] == gitlab_job_fixture["name"]


def test_get_trigger_phrases_regex(
    patch_jjb: Any, gitlab_job_fixture: dict[str, Any]
) -> None:
    jjb = JJB([])
    assert jjb.get_trigger_phrases_regex(gitlab_job_fixture) == "my_trigger_regex.*"


def test_get_gitlab_webhook_trigger(
    patch_jjb: Any, gitlab_job_fixture: dict[str, Any]
) -> None:
    jjb = JJB([])
    assert jjb.get_gitlab_webhook_trigger(gitlab_job_fixture) == []


def test_get_gitlab_webhook_trigger_pr_check(
    patch_jjb: Any, gitlab_pr_check_job_fixture: dict[str, Any]
) -> None:
    jjb = JJB([])
    assert jjb.get_gitlab_webhook_trigger(gitlab_pr_check_job_fixture) == ["mr", "note"]


def test_get_gitlab_webhook_trigger_build(
    patch_jjb: Any, gitlab_build_job_fixture: dict[str, Any]
) -> None:
    jjb = JJB([])
    assert jjb.get_gitlab_webhook_trigger(gitlab_build_job_fixture) == ["push"]


def test_get_gitlab_webhook_trigger_test(
    patch_jjb: Any, gitlab_test_job_fixture: dict[str, Any]
) -> None:
    jjb = JJB([])
    assert jjb.get_gitlab_webhook_trigger(gitlab_test_job_fixture) == ["note"]


def test_print_diff(
    patch_jjb: Any, patch_logging: MagicMock, patch_et_parse: MagicMock
) -> None:
    jjb = JJB([])
    jjb.print_diff(
        ["throughput/jjb/desired/ci-int/group-project/config.xml"],
        "throughput/jjb/desired",
        "create",
    )
    patch_logging.info.assert_called_once_with([
        "create",
        "job",
        "ci-int",
        "group-project",
    ])


def test_print_diff_with_invalid_job_name(
    patch_jjb: Any, patch_logging: MagicMock, patch_et_parse: MagicMock
) -> None:
    jjb = JJB([])
    with pytest.raises(ValueError) as e_info:
        jjb.print_diff(
            ["throughput/jjb/desired/ci-int/group/project/config.xml"],
            "throughput/jjb/desired",
            "create",
        )
    assert str(e_info.value) == "Invalid job name contains '/' in ci-int: group/project"



def test_get_jobs_parses_jjb_templates() -> None:
    """Test that get_jobs parses JJB templates and generates job definitions using real jenkins-jobs library"""
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "jjb"
    ini_path = fixtures_dir / "jenkins.ini"
    config_path = fixtures_dir / "jobs.yaml"
    
    with tempfile.TemporaryDirectory() as temp_dir:
        instance_ini = Path(temp_dir) / "jenkins.ini"
        jjb_config = Path(temp_dir) / "config.yaml"
        
        instance_ini.write_text(ini_path.read_text())
        jjb_config.write_text(config_path.read_text())
        
        jjb = JJB(configs=[], print_only=True)
        
        jobs = jjb.get_jobs(temp_dir, "jenkins")
        
        assert isinstance(jobs, list)
        assert len(jobs) == 2
        
        job_names = [job['name'] for job in jobs]
        assert 'sample-service-build' in job_names
        assert 'sample-service-pr-check' in job_names
        
        for job in jobs:
            assert 'name' in job
            assert 'properties' in job
            assert 'github' in job['properties'][0]
            assert job['properties'][0]['github']['url'] == 'https://github.com/example/sample-service'
