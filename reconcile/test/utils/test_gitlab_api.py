from typing import Any
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import (
    CurrentUser,
    Project,
    ProjectIssue,
    ProjectIssueManager,
    ProjectIssueNoteManager,
    ProjectLabel,
    ProjectLabelManager,
    ProjectMergeRequest,
    ProjectMergeRequestManager,
    ProjectMergeRequestNote,
    ProjectMergeRequestNoteManager,
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

@pytest.fixture
def mocked_gitlab_request(mocker: MockerFixture) -> Any:
    """replaces the instriumentation with a mock"""
    return mocker.patch("reconcile.utils.gitlab_api.gitlab_request")


@pytest.fixture
def mocked_gl(mocker: MockerFixture) -> Any:
    mocked_gl = mocker.patch("reconcile.utils.gitlab_api.gitlab").Gitlab.return_value
    mocker.patch("reconcile.utils.gitlab_api.SecretReader", autospec=True)
    return mocked_gl


@pytest.fixture
def mocked_gitlab_api(instance, mocked_gl: Any, mocked_gitlab_request: Any) -> GitLabApi:
    """creates a gitlab api instance where the internal gitlab client
    is replaced with a mock"""
    gitlab_api = GitLabApi(instance, project_id=1)
    # reset the mock as the ctor tries to be smart
    mocked_gitlab_request.reset_mock()
    return gitlab_api


def test_remove_label_from_merge_request(
    mocked_gitlab_request: Any,
) -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = current_labels

    GitLabApi.remove_label(mr, to_be_removed_label)

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2
    assert mr.labels == [expected_label]
    mr.save.assert_called_once()


def test_remove_label_from_issue(
    mocked_gitlab_request: Any,
) -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    issue = create_autospec(ProjectIssue)
    issue.manager = create_autospec(ProjectIssueManager)
    issue.manager.get.return_value = issue
    issue.labels = current_labels

    GitLabApi.remove_label(issue, to_be_removed_label)

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2
    assert issue.labels == [expected_label]
    issue.save.assert_called_once()


def test_remove_labels_from_merge_request(
    mocked_gitlab_request: Any,
) -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = current_labels

    GitLabApi.remove_labels(mr, [to_be_removed_label])

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2
    assert mr.labels == [expected_label]
    mr.save.assert_called_once()


def test_remove_labels_from_issue(
    mocked_gitlab_request: Any,
) -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    issue = create_autospec(ProjectIssue)
    issue.manager = create_autospec(ProjectIssueManager)
    issue.manager.get.return_value = issue
    issue.labels = current_labels

    GitLabApi.remove_labels(issue, [to_be_removed_label])

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2
    assert issue.labels == [expected_label]
    issue.save.assert_called_once()


def test_add_label_with_note_to_merge_request(
    mocked_gitlab_request: Any,
) -> None:
    existing_label = "a"
    new_label = "b"
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = [existing_label]
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)

    GitLabApi.add_label_with_note(mr, new_label)

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 3
    assert mr.labels == [existing_label, new_label]
    mr.notes.create.assert_called_once_with({
        "body": f"item has been marked as {new_label}. "
        f"to remove say `/{new_label} cancel`",
    })
    mr.save.assert_called_once()


def test_add_label_with_note_to_issue(
    mocked_gitlab_request: Any,
) -> None:
    existing_label = "a"
    new_label = "b"
    issue = create_autospec(ProjectIssue)
    issue.manager = create_autospec(ProjectIssueManager)
    issue.manager.get.return_value = issue
    issue.labels = [existing_label]
    issue.notes = create_autospec(ProjectIssueNoteManager)

    mocked_gitlab_request.reset_mock()

    GitLabApi.add_label_with_note(issue, new_label)

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 3
    assert issue.labels == [existing_label, new_label]
    issue.notes.create.assert_called_once_with({
        "body": f"item has been marked as {new_label}. "
        f"to remove say `/{new_label} cancel`",
    })
    issue.save.assert_called_once()


def test_add_label_to_merge_request(
    mocked_gitlab_request: Any,
) -> None:
    existing_label = "a"
    new_label = "b"
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = [existing_label]

    GitLabApi.add_label_to_merge_request(mr, new_label)

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2
    assert mr.labels == [existing_label, new_label]
    mr.save.assert_called_once()


def test_add_labels_to_merge_request(
    mocked_gitlab_request: Any,
) -> None:
    existing_label = "a"
    new_label = "b"
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = [existing_label]

    GitLabApi.add_labels_to_merge_request(mr, [new_label])

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2
    assert mr.labels == [existing_label, new_label]
    mr.save.assert_called_once()


def test_set_labels_on_merge_request(
    mocked_gitlab_request: Any,
) -> None:
    existing_label = "a"
    new_label = "b"
    extra_existing_label = "c"
    refreshed_mr = create_autospec(ProjectMergeRequest)
    refreshed_mr.labels = [existing_label, extra_existing_label]
    mr = create_autospec(ProjectMergeRequest)
    mr.labels = [existing_label]
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = refreshed_mr

    GitLabApi.set_labels_on_merge_request(mr, [new_label])

    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2
    assert set(mr.labels) == {extra_existing_label, new_label}
    mr.save.assert_called_once()


def test_add_comment_to_merge_request(
    mocked_gitlab_request: Any,
) -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)
    body = "some body"

    GitLabApi.add_comment_to_merge_request(mr, body)

    mocked_gitlab_request.labels.return_value.inc.assert_called_once()
    mr.notes.create.assert_called_once_with({
        "body": body,
    })


def test_get_merge_request_comments(
    mocked_gitlab_request: Any,
) -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.author = {"username": "author_a"}
    mr.description = "description"
    mr.created_at = "2023-01-01T00:00:00Z"
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)
    note = create_autospec(ProjectMergeRequestNote)
    note.author = {"username": "author_b"}
    note.body = "body"
    note.created_at = "2023-01-02T00:00:00Z"
    note.id = 2
    note.system = False
    mr.notes.list.return_value = [note]

    comments = GitLabApi.get_merge_request_comments(mr, True)

    expected_comments = [
        {
            "username": "author_a",
            "body": "description",
            "created_at": "2023-01-01T00:00:00Z",
            "id": 0,
        },
        {
            "username": "author_b",
            "body": "body",
            "created_at": "2023-01-02T00:00:00Z",
            "id": 2,
            "note": note,
        },
    ]
    assert comments == expected_comments
    mocked_gitlab_request.labels.return_value.inc.assert_called_once()


def test_delete_comment(
    mocked_gitlab_request: Any,
) -> None:
    note = create_autospec(ProjectMergeRequestNote)

    GitLabApi.delete_comment(note)

    mocked_gitlab_request.labels.return_value.inc.assert_called_once()
    note.delete.assert_called_once_with()


def test_delete_merge_request_comments(
    instance: dict,
    mocked_gitlab_request: Any,
    mocked_gl: Any,
    mocked_gitlab_api: GitLabApi,
) -> None:
    mocked_gitlab_api.user = create_autospec(CurrentUser, username="author")

    mr = create_autospec(ProjectMergeRequest)
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)

    note = create_autospec(ProjectMergeRequestNote)
    note.author = {"username": "author"}
    note.body = "body abc"
    note.created_at = "2023-01-02T00:00:00Z"
    note.id = 2
    note.system = False

    mr.notes.list.return_value = [note]

    mocked_gitlab_api.delete_merge_request_comments(mr, "body")

    note.delete.assert_called_once_with()
    assert mocked_gitlab_request.labels.return_value.inc.call_count == 2


def test_get_project_labels(
    instance: dict,
    mocked_gl: Any,
    mocked_gitlab_api: GitLabApi,
    mocked_gitlab_request: Any
) -> None:
    label = create_autospec(ProjectLabel)
    label.name = "a"
    project = create_autospec(Project)
    project.labels = create_autospec(ProjectLabelManager)
    project.labels.list.return_value = [label]

    mocked_gitlab_api.project = project

    labels = mocked_gitlab_api.get_project_labels()

    assert labels == {"a"}
    mocked_gitlab_request.labels.return_value.inc.assert_called_once()


def test_get_merge_request_changed_paths(
        mocked_gitlab_request: Any
) -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.changes.return_value = {
        "changes": [
            {
                "old_path": "path",
                "new_path": "path",
            }
        ]
    }

    paths = GitLabApi.get_merge_request_changed_paths(mr)

    mocked_gitlab_request.labels.return_value.inc.assert_called_once()
    assert paths == ["path"]


def test_get_merge_request_author_username(
    mocked_gitlab_request: Any,
) -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.author = {"username": "author_a"}

    username = GitLabApi.get_merge_request_author_username(mr)

    assert username == "author_a"
    mocked_gitlab_request.labels.return_value.inc.assert_not_called()


def test_mr_exist(
    instance: dict,
    mocked_gl: Any,
    mocked_gitlab_api: GitLabApi,
    mocked_gitlab_request: Any
) -> None:
    project = create_autospec(Project)
    project.mergerequests = create_autospec(ProjectMergeRequestManager)
    mr = create_autospec(ProjectMergeRequest, title="title")
    project.mergerequests.list.return_value = [mr]
    mocked_gitlab_api.project = project


    exists = mocked_gitlab_api.mr_exists("title")

    assert exists is True
    mocked_gitlab_request.labels.return_value.inc.assert_called_once()


def test_refresh_labels_for_merge_request(
    mocked_gitlab_request: Any
) -> None:
    manager = create_autospec(ProjectMergeRequestManager)

    mr = create_autospec(ProjectMergeRequest)
    mr.get_id.return_value = 1
    mr.labels = ["existing_label"]
    mr.manager = manager

    refreshed_mr = create_autospec(ProjectMergeRequest)
    refreshed_mr.labels = ["existing_label", "new_label"]

    manager.get.return_value = refreshed_mr

    GitLabApi.refresh_labels(mr)

    assert mr.labels == ["existing_label", "new_label"]
    mocked_gitlab_request.labels.return_value.inc.assert_called_once_with()
    manager.get.assert_called_once_with(1)


def test_refresh_labels_for_issue(
    mocked_gitlab_request: Any,
) -> None:
    manager = create_autospec(ProjectIssueManager)

    issue = create_autospec(ProjectIssue)
    issue.get_id.return_value = 1
    issue.labels = ["existing_label"]
    issue.manager = manager

    refreshed_issue = create_autospec(ProjectIssue)
    refreshed_issue.labels = ["existing_label", "new_label"]

    manager.get.return_value = refreshed_issue

    GitLabApi.refresh_labels(issue)

    assert issue.labels == ["existing_label", "new_label"]
    mocked_gitlab_request.labels.return_value.inc.assert_called_once_with()
    manager.get.assert_called_once_with(1)
