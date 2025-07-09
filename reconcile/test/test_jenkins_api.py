from unittest.mock import create_autospec

import pytest
from pytest_mock import MockerFixture
from requests import Response

from reconcile.utils.jenkins_api import JenkinsApi


@pytest.fixture
def jenkins_api() -> JenkinsApi:
    return JenkinsApi("http://example.com", "user", "password", ssl_verify=False)


def test_get_jobs_state(
    jenkins_api: JenkinsApi,
    mocker: MockerFixture,
) -> None:
    mocked_requests = mocker.patch("reconcile.utils.jenkins_api.requests")
    mocked_response = create_autospec(Response)
    mocked_requests.get.return_value = mocked_response
    build = {
        "_class": "hudson.model.FreeStyleBuild",
        "actions": [
            {"_class": "hudson.model.CauseAction"},
            {},
            {
                "_class": "hudson.plugins.git.util.BuildData",
                "lastBuiltRevision": {
                    "SHA1": "1283f348a8364d925385388ae2943903c0bdd86a"
                },
            },
        ],
        "number": 1,
        "result": "SUCCESS",
    }
    mocked_response.json.return_value = {
        "_class": "hudson.model.Hudson",
        "jobs": [
            {
                "_class": "hudson.model.FreeStyleProject",
                "name": "job1",
                "builds": [build],
            },
        ],
    }
    expected_build = build | {"commit_sha": "1283f348a8364d925385388ae2943903c0bdd86a"}
    expected_job_state = {"job1": [expected_build]}

    job_state = jenkins_api.get_jobs_state()

    assert job_state == expected_job_state
