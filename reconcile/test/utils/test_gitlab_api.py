from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import (
    ProjectIssue,
    ProjectMergeRequest,
)
from pytest_mock import MockerFixture
from requests.exceptions import ConnectTimeout

from reconcile.utils.gitlab_api import GitLabApi


def test_gitlab_client_timeout(mocker, patch_sleep):
    secret_reader_mock = mocker.patch(
        "reconcile.utils.gitlab_api.SecretReader", autospec=True
    )
    secret_reader_mock.return_value.read.return_value = "0000000"

    instance = {
        "url": "http://198.18.0.1",  # Non routable ip address
        "token": "non-existent-token",
        "sslVerify": False,
    }

    with pytest.raises(ConnectTimeout):
        GitLabApi(instance, timeout=0.1)


@pytest.fixture
def instance() -> dict:
    return {
        "url": "http://some-url",
        "token": "some-token",
        "sslVerify": False,
    }


def test_remove_label_from_merge_request(
    instance: dict,
    mocker: MockerFixture,
) -> None:
    mocker.patch("reconcile.utils.gitlab_api.gitlab")
    mocked_gitlab_request = mocker.patch("reconcile.utils.gitlab_api.gitlab_request")
    mocker.patch("reconcile.utils.gitlab_api.SecretReader", autospec=True)

    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    mr = create_autospec(ProjectMergeRequest)
    mr.labels = current_labels

    gitlab_api = GitLabApi(
        instance,
        project_id=1,
    )
    mocked_gitlab_request.reset_mock()

    gitlab_api.remove_label(mr, to_be_removed_label)

    mocked_gitlab_request.labels.return_value.inc.assert_called_once()
    assert mr.labels == ["a"]
    mr.save.assert_called_once()


def test_remove_label_from_issue(
    instance: dict,
    mocker: MockerFixture,
) -> None:
    mocker.patch("reconcile.utils.gitlab_api.gitlab")
    mocked_gitlab_request = mocker.patch("reconcile.utils.gitlab_api.gitlab_request")
    mocker.patch("reconcile.utils.gitlab_api.SecretReader", autospec=True)

    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    issue = create_autospec(ProjectIssue)
    issue.labels = current_labels

    gitlab_api = GitLabApi(
        instance,
        project_id=1,
    )
    mocked_gitlab_request.reset_mock()

    gitlab_api.remove_label(issue, to_be_removed_label)

    mocked_gitlab_request.labels.return_value.inc.assert_called_once()
    assert issue.labels == ["a"]
    issue.save.assert_called_once()
