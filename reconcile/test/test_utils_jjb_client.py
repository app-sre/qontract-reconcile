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
def patch_jjb(mocker, github_job_fixture, gitlab_job_fixture):
    mocker.patch(
        "reconcile.utils.jjb_client.JJB.__init__", return_value=None, autospec=True
    )
    return mocker.patch(
        "reconcile.utils.jjb_client.JJB.get_all_jobs",
        return_value={"ci": [github_job_fixture, gitlab_job_fixture]},
        autospec=True,
    )


def test_get_job_by_repo_url(patch_jjb, gitlab_job_fixture):
    jjb = JJB(None)
    job = jjb.get_job_by_repo_url(
        "http://mygilabinstance.org/service/foobar", "pr-check"
    )
    assert job["name"] == gitlab_job_fixture["name"]


def test_get_trigger_phrases_regex(patch_jjb, gitlab_job_fixture):
    jjb = JJB(None)
    assert jjb.get_trigger_phrases_regex(gitlab_job_fixture) == "my_trigger_regex.*"
