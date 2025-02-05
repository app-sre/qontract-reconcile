import pytest

from reconcile.utils.jjb_client import JJB


@pytest.fixture
def github_job_fixture():
    return {
        "name": "service-foobar2-build",
        "properties": [{"github": {"url": "http://github.com"}}],
        "triggers": [
            {"github-pull-request": {"trigger-phrase": ".*"}},
        ],
    }


@pytest.fixture
def gitlab_job_fixture():
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
def gitlab_pr_check_job_fixture():
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
def gitlab_build_job_fixture():
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
def gitlab_test_job_fixture():
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
def patch_jjb(mocker, github_job_fixture, gitlab_job_fixture):
    mocker.patch(
        "reconcile.utils.jjb_client.JJB.__init__", return_value=None, autospec=True
    )
    return mocker.patch(
        "reconcile.utils.jjb_client.JJB.get_all_jobs",
        return_value={"ci": [github_job_fixture, gitlab_job_fixture]},
        autospec=True,
    )


@pytest.fixture
def patch_logging(mocker):
    return mocker.patch("reconcile.utils.jjb_client.logging")


@pytest.fixture
def patch_et_parse(mocker):
    et = mocker.patch("reconcile.utils.jjb_client.et")
    et.parse.return_value.getroot.return_value.tag = "job"
    return et


def test_get_job_by_repo_url(patch_jjb, gitlab_job_fixture):
    jjb = JJB(None)
    job = jjb.get_job_by_repo_url(
        "http://mygilabinstance.org/service/foobar", "pr-check"
    )
    assert job["name"] == gitlab_job_fixture["name"]


def test_get_trigger_phrases_regex(patch_jjb, gitlab_job_fixture):
    jjb = JJB(None)
    assert jjb.get_trigger_phrases_regex(gitlab_job_fixture) == "my_trigger_regex.*"


def test_get_gitlab_webhook_trigger(patch_jjb, gitlab_job_fixture):
    jjb = JJB(None)
    assert jjb.get_gitlab_webhook_trigger(gitlab_job_fixture) == []


def test_get_gitlab_webhook_trigger_pr_check(patch_jjb, gitlab_pr_check_job_fixture):
    jjb = JJB(None)
    assert jjb.get_gitlab_webhook_trigger(gitlab_pr_check_job_fixture) == ["mr", "note"]


def test_get_gitlab_webhook_trigger_build(patch_jjb, gitlab_build_job_fixture):
    jjb = JJB(None)
    assert jjb.get_gitlab_webhook_trigger(gitlab_build_job_fixture) == ["push"]


def test_get_gitlab_webhook_trigger_test(patch_jjb, gitlab_test_job_fixture):
    jjb = JJB(None)
    assert jjb.get_gitlab_webhook_trigger(gitlab_test_job_fixture) == ["note"]


def test_print_diff(patch_jjb, patch_logging, patch_et_parse):
    jjb = JJB(None)
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


def test_print_diff_with_invalid_job_name(patch_jjb, patch_logging, patch_et_parse):
    jjb = JJB(None)
    with pytest.raises(ValueError) as e_info:
        jjb.print_diff(
            ["throughput/jjb/desired/ci-int/group/project/config.xml"],
            "throughput/jjb/desired",
            "create",
        )
    assert str(e_info.value) == "Invalid job name contains '/' in ci-int: group/project"
