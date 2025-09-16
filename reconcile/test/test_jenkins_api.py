from unittest.mock import call, create_autospec

import pytest
from pytest_mock import MockerFixture
from requests import Response

from reconcile.utils.jenkins_api import JenkinsApi


@pytest.fixture
def user() -> str:
    return "user"


@pytest.fixture
def password() -> str:
    return "password"


@pytest.fixture
def jenkins_api(user: str, password: str) -> JenkinsApi:
    return JenkinsApi("http://example.com", user, password, ssl_verify=False)


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


def test_trigger_job_build(
    jenkins_api: JenkinsApi, mocker: MockerFixture, user: str, password: str
) -> None:
    mocked_requests = mocker.patch("reconcile.utils.jenkins_api.requests")
    first_mocked_response = create_autospec(Response)
    first_mocked_response.json.return_value = {
        "_class": "hudson.security.csrf.DefaultCrumbIssuer",
        "crumb": "058d22a8f4805175d41425b4ad8afa81117aa813a19d4918a6af5f83abe42e37",
        "crumbRequestField": "Jenkins-Crumb",
    }
    second_mocked_response = create_autospec(Response)
    second_mocked_response.json.return_value = {
        "_class": "hudson.model.FreeStyleProject",
        "property": [
            {"_class": "com.coravy.hudson.plugins.github.GithubProjectProperty"},
            {
                "_class": "com.dabsquared.gitlabjenkins.connection.GitLabConnectionProperty"
            },
        ],
    }

    mocked_requests.get.side_effect = [
        first_mocked_response,
        second_mocked_response,
    ]

    jenkins_api.trigger_job("test")

    mocked_requests.get.assert_has_calls([
        call(
            "http://example.com/crumbIssuer/api/json",
            verify=False,
            auth=(user, password),
            timeout=60,
        ),
        call(
            "http://example.com/job/test/api/json?tree=property[parameterDefinitions[*]]",
            verify=False,
            auth=(user, password),
            timeout=60,
        ),
    ])

    mocked_requests.post.assert_called_once_with(
        "http://example.com/job/test/build",
        auth=(user, password),
        timeout=60,
        verify=False,
    )


def test_trigger_job_build_with_parameters(
    jenkins_api: JenkinsApi, mocker: MockerFixture, user: str, password: str
) -> None:
    mocked_requests = mocker.patch("reconcile.utils.jenkins_api.requests")
    first_mocked_response = create_autospec(Response)
    first_mocked_response.json.return_value = {
        "_class": "hudson.security.csrf.DefaultCrumbIssuer",
        "crumb": "78ad8e9fb370431c261b8928d7276efc3cd1831b47b6103adf946d53288135d8",
        "crumbRequestField": "Jenkins-Crumb",
    }
    second_mocked_response = create_autospec(Response)
    second_mocked_response.json.return_value = {
        "_class": "hudson.model.FreeStyleProject",
        "property": [
            {"_class": "com.coravy.hudson.plugins.github.GithubProjectProperty"},
            {
                "_class": "com.dabsquared.gitlabjenkins.connection.GitLabConnectionProperty"
            },
            {
                "_class": "hudson.model.ParametersDefinitionProperty",
                "parameterDefinitions": [
                    {
                        "_class": "hudson.model.StringParameterDefinition",
                        "defaultParameterValue": {
                            "_class": "hudson.model.StringParameterValue"
                        },
                        "description": "Path to the suite which Ginkgo should run",
                        "name": "SUITE_PATH",
                        "type": "StringParameterDefinition",
                    },
                    {
                        "_class": "hudson.model.StringParameterDefinition",
                        "defaultParameterValue": {
                            "_class": "hudson.model.StringParameterValue"
                        },
                        "description": "Completion timeout for Ginkgo based API tests.",
                        "name": "TIMEOUT",
                        "type": "StringParameterDefinition",
                    },
                ],
            },
        ],
    }
    mocked_requests.get.side_effect = [
        first_mocked_response,
        second_mocked_response,
    ]

    jenkins_api.trigger_job("test")

    mocked_requests.get.assert_has_calls([
        call(
            "http://example.com/crumbIssuer/api/json",
            verify=False,
            auth=("user", "password"),
            timeout=60,
        ),
        call(
            "http://example.com/job/test/api/json?tree=property[parameterDefinitions[*]]",
            verify=False,
            auth=("user", "password"),
            timeout=60,
        ),
    ])

    mocked_requests.post.assert_called_once_with(
        "http://example.com/job/test/buildWithParameters",
        auth=(user, password),
        timeout=60,
        verify=False,
    )
