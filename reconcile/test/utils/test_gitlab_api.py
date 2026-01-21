import io
import os
import tarfile
from collections.abc import Mapping
from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import (
    CurrentUser,
    Group,
    GroupManager,
    GroupMember,
    GroupMemberManager,
    GroupProject,
    GroupProjectManager,
    PersonalAccessToken,
    PersonalAccessTokenManager,
    Project,
    ProjectFileManager,
    ProjectIssue,
    ProjectIssueManager,
    ProjectIssueNoteManager,
    ProjectLabel,
    ProjectLabelManager,
    ProjectManager,
    ProjectMemberAll,
    ProjectMemberAllManager,
    ProjectMergeRequest,
    ProjectMergeRequestApproval,
    ProjectMergeRequestApprovalManager,
    ProjectMergeRequestManager,
    ProjectMergeRequestNote,
    ProjectMergeRequestNoteManager,
    ProjectMergeRequestPipeline,
    ProjectMergeRequestPipelineManager,
    ProjectMergeRequestResourceLabelEvent,
    ProjectMergeRequestResourceLabelEventManager,
)
from pytest_mock import MockerFixture
from requests.exceptions import ConnectTimeout

from reconcile.utils.gitlab_api import Assignment, Comment, GitLabApi


def test_gitlab_client_timeout(mocker: MockerFixture, patch_sleep: None) -> None:
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
def mocked_gl(mocker: MockerFixture) -> Mock:
    mocked_gl = mocker.patch(
        "reconcile.utils.gitlab_api.Gitlab", autospec=True
    ).return_value
    mocked_gl.user = create_autospec(CurrentUser)
    mocked_gl.projects = create_autospec(ProjectManager)
    mocked_gl.groups = create_autospec(GroupManager)
    mocked_gl.personal_access_tokens = create_autospec(PersonalAccessTokenManager)
    mocker.patch("reconcile.utils.gitlab_api.SecretReader", autospec=True)
    return mocked_gl


@pytest.fixture
def mocked_gitlab_api(
    instance: Mapping,
    mocked_gl: Mock,
) -> GitLabApi:
    """creates a gitlab api instance where the internal gitlab client
    is replaced with a mock"""
    return GitLabApi(instance, project_id=1)


def test_gitlab_api_init(
    instance: Mapping,
    mocker: MockerFixture,
) -> None:
    """Test that the GitLabApi class is initialized correctly"""
    mocked_gitlab = mocker.patch("reconcile.utils.gitlab_api.Gitlab", autospec=True)
    mocked_user = create_autospec(CurrentUser)
    mocked_gitlab.return_value.user = mocked_user
    mocked_project_manager = create_autospec(ProjectManager)
    mocked_gitlab.return_value.projects = mocked_project_manager
    mocked_secret_reader = mocker.patch(
        "reconcile.utils.gitlab_api.SecretReader", autospec=True
    )
    mocked_secret_reader.return_value.read.return_value = "private-token"
    mocked_gitlab_request = mocker.patch("reconcile.utils.gitlab_api.gitlab_request")
    mocked_session = mocker.patch(
        "reconcile.utils.gitlab_api.InstrumentedSession", autospec=True
    )
    mocker.patch.dict(os.environ, {"INTEGRATION_NAME": "test-gitlab"})

    gitlab_api = GitLabApi(instance, project_id=1)

    mocked_gitlab.assert_called_once_with(
        instance["url"],
        private_token="private-token",
        ssl_verify=False,
        timeout=30,
        session=mocked_session.return_value,
        per_page=100,
        pagination="keyset",
    )
    assert gitlab_api.server == instance["url"]
    assert gitlab_api.ssl_verify is False
    assert gitlab_api.session == mocked_session.return_value
    assert gitlab_api.gl == mocked_gitlab.return_value
    assert gitlab_api.user == mocked_user
    assert gitlab_api.project == mocked_project_manager.get.return_value
    mocked_secret_reader.assert_called_once_with(settings=None)
    mocked_secret_reader.return_value.read.assert_called_once_with("some-token")
    mocked_session.assert_called_once_with(mocked_gitlab_request.labels.return_value)
    mocked_gitlab_request.labels.assert_called_once_with(integration="test-gitlab")


def test_remove_label_from_merge_request() -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = current_labels

    GitLabApi.remove_label(mr, to_be_removed_label)

    assert mr.labels == [expected_label]
    mr.save.assert_called_once()


def test_remove_label_from_issue() -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    issue = create_autospec(ProjectIssue)
    issue.manager = create_autospec(ProjectIssueManager)
    issue.manager.get.return_value = issue
    issue.labels = current_labels

    GitLabApi.remove_label(issue, to_be_removed_label)

    assert issue.labels == [expected_label]
    issue.save.assert_called_once()


def test_remove_labels_from_merge_request() -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = current_labels

    GitLabApi.remove_labels(mr, [to_be_removed_label])

    assert mr.labels == [expected_label]
    mr.save.assert_called_once()


def test_remove_labels_from_issue() -> None:
    expected_label = "a"
    to_be_removed_label = "b"
    current_labels = [expected_label, to_be_removed_label]
    issue = create_autospec(ProjectIssue)
    issue.manager = create_autospec(ProjectIssueManager)
    issue.manager.get.return_value = issue
    issue.labels = current_labels

    GitLabApi.remove_labels(issue, [to_be_removed_label])

    assert issue.labels == [expected_label]
    issue.save.assert_called_once()


def test_add_label_with_note_to_merge_request() -> None:
    existing_label = "a"
    new_label = "b"
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = [existing_label]
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)

    GitLabApi.add_label_with_note(mr, new_label)

    assert mr.labels == [existing_label, new_label]
    mr.notes.create.assert_called_once_with({
        "body": f"item has been marked as {new_label}. "
        f"to remove say `/{new_label} cancel`",
    })
    mr.save.assert_called_once()


def test_add_label_with_note_to_issue() -> None:
    existing_label = "a"
    new_label = "b"
    issue = create_autospec(ProjectIssue)
    issue.manager = create_autospec(ProjectIssueManager)
    issue.manager.get.return_value = issue
    issue.labels = [existing_label]
    issue.notes = create_autospec(ProjectIssueNoteManager)

    GitLabApi.add_label_with_note(issue, new_label)

    assert issue.labels == [existing_label, new_label]
    issue.notes.create.assert_called_once_with({
        "body": f"item has been marked as {new_label}. "
        f"to remove say `/{new_label} cancel`",
    })
    issue.save.assert_called_once()


def test_add_label_to_merge_request() -> None:
    existing_label = "a"
    new_label = "b"
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = [existing_label]

    GitLabApi.add_label_to_merge_request(mr, new_label)

    assert mr.labels == [existing_label, new_label]
    mr.save.assert_called_once()


def test_add_labels_to_merge_request() -> None:
    existing_label = "a"
    new_label = "b"
    mr = create_autospec(ProjectMergeRequest)
    mr.manager = create_autospec(ProjectMergeRequestManager)
    mr.manager.get.return_value = mr
    mr.labels = [existing_label]

    GitLabApi.add_labels_to_merge_request(mr, [new_label])

    assert mr.labels == [existing_label, new_label]
    mr.save.assert_called_once()


def test_set_labels_on_merge_request() -> None:
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

    assert set(mr.labels) == {extra_existing_label, new_label}
    mr.save.assert_called_once()


def test_add_comment_to_merge_request() -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)
    body = "some body"

    GitLabApi.add_comment_to_merge_request(mr, body)

    mr.notes.create.assert_called_once_with({
        "body": body,
    })


def test_get_merge_request_comments() -> None:
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
    mr.approvals = create_autospec(ProjectMergeRequestApprovalManager)
    approvals = create_autospec(ProjectMergeRequestApproval)
    approvals.approved_by = [
        {
            "user": {"id": 3, "username": "author_c"},
            "approved_at": "2023-01-03T00:00:00Z",
        },
    ]
    mr.approvals.get.return_value = approvals

    comments = GitLabApi.get_merge_request_comments(mr, True, True, "/sup")

    expected_comments = [
        Comment(
            username="author_a",
            body="description",
            created_at="2023-01-01T00:00:00Z",
            id=0,
        ),
        Comment(
            username="author_c",
            body="/sup",
            created_at="2023-01-03T00:00:00Z",
            id=3,
        ),
        Comment(
            username="author_b",
            body="body",
            created_at="2023-01-02T00:00:00Z",
            id=2,
            note=note,
        ),
    ]
    assert comments == expected_comments
    mr.notes.list.assert_called_once_with(iterator=True)
    mr.approvals.get.assert_called_once()


def test_delete_comment() -> None:
    note = create_autospec(ProjectMergeRequestNote)

    GitLabApi.delete_comment(note)

    note.delete.assert_called_once_with()


def test_delete_merge_request_comments(
    instance: dict,
    mocked_gitlab_api: GitLabApi,
) -> None:
    mocked_gitlab_api.user.username = "author"
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


def test_get_project_labels(
    mocked_gitlab_api: GitLabApi,
) -> None:
    label = create_autospec(ProjectLabel)
    label.name = "a"
    project = create_autospec(Project)
    project.labels = create_autospec(ProjectLabelManager)
    project.labels.list.return_value = [label]

    mocked_gitlab_api.project = project

    labels = mocked_gitlab_api.get_project_labels()

    assert labels == {"a"}
    project.labels.list.assert_called_once_with(iterator=True)


def test_get_merge_request_changed_paths() -> None:
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

    assert paths == ["path"]


def test_get_merge_request_author_username() -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.author = {"username": "author_a"}

    username = GitLabApi.get_merge_request_author_username(mr)

    assert username == "author_a"


def test_mr_exist(
    instance: dict,
    mocked_gitlab_api: GitLabApi,
) -> None:
    project = create_autospec(Project)
    project.mergerequests = create_autospec(ProjectMergeRequestManager)
    mr = create_autospec(ProjectMergeRequest, title="title")
    project.mergerequests.list.return_value = [mr]
    mocked_gitlab_api.project = project

    exists = mocked_gitlab_api.mr_exists("title")

    assert exists is True


def test_refresh_labels_for_merge_request() -> None:
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
    manager.get.assert_called_once_with(1)


def test_refresh_labels_for_issue() -> None:
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
    manager.get.assert_called_once_with(1)


def test_get_group_members(
    mocked_gl: Any,
    mocked_gitlab_api: GitLabApi,
) -> None:
    user = create_autospec(
        GroupMember,
        username="small",
        access_level=50,
        id="123",
    )
    # group bots should be ignored
    group_bot = create_autospec(
        GroupMember,
        username="group_123_bot_deadbeef",
        access_level=50,
        id="121",
    )
    group = create_autospec(Group)
    group.members = create_autospec(GroupMemberManager)
    group.members.list.return_value = [user, group_bot]

    groups = create_autospec(GroupManager)
    groups.get.return_value = group
    mocked_gl.groups = groups

    assert mocked_gitlab_api.get_group_members(group) == [user]
    group.members.list.assert_called_once_with(iterator=True)


def test_share_project_with_group_positive(
    mocked_gitlab_api: GitLabApi,
) -> None:
    project = create_autospec(Project)
    mocked_gitlab_api.share_project_with_group(project, 1111, 40)
    project.share.assert_called_once_with(1111, 40)


def test_get_project_maintainers(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    mocked_project = mocked_gl.projects.get.return_value
    mocked_project.members_all = create_autospec(ProjectMemberAllManager)
    member = create_autospec(
        ProjectMemberAll,
        id="1",
        username="m",
        access_level=40,
    )
    mocked_project.members_all.list.return_value = [member]
    query = {
        "user_ids": "1",
    }

    result = mocked_gitlab_api.get_project_maintainers(query=query)

    assert result == ["m"]
    mocked_project.members_all.list.assert_called_once_with(
        iterator=True,
        query_parameters=query,
    )


def test_get_app_sre_group_users(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    mocked_group = mocked_gl.groups.get.return_value
    mocked_group.members = create_autospec(GroupMemberManager)
    expected_members = [
        create_autospec(GroupMember, id="1", username="m1"),
    ]
    mocked_group.members.list.return_value = expected_members

    members = mocked_gitlab_api.get_app_sre_group_users()

    assert members == expected_members
    mocked_gl.groups.get.assert_called_once_with("app-sre")
    mocked_group.members.list.assert_called_once_with(get_all=True)


def test_get_group_id_and_projects(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    group = create_autospec(Group, id="1")
    mocked_gl.groups.get.return_value = group
    group.projects = create_autospec(GroupProjectManager)
    project = create_autospec(GroupProject)
    project.name = "project_name"
    group.projects.list.return_value = [project]

    group_id, project_names = mocked_gitlab_api.get_group_id_and_projects("group_name")

    assert group_id == "1"
    assert project_names == {"project_name"}


def test_get_issues(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    project = mocked_gl.projects.get.return_value
    project.issues = create_autospec(ProjectIssueManager)
    expected_issue = create_autospec(ProjectIssue)
    project.issues.list.return_value = [expected_issue]

    issue = mocked_gitlab_api.get_issues(state="opened")

    assert issue == [expected_issue]
    project.issues.list.assert_called_once_with(state="opened", get_all=True)


def test_get_merge_requests(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    project = mocked_gl.projects.get.return_value
    project.mergerequests = create_autospec(ProjectMergeRequestManager)
    expected_mr = create_autospec(ProjectMergeRequest)
    project.mergerequests.list.return_value = [expected_mr]

    mr = mocked_gitlab_api.get_merge_requests(state="opened")

    assert mr == [expected_mr]
    project.mergerequests.list.assert_called_once_with(
        state="opened",
        order_by="created_at",
        get_all=True,
    )


def test_get_merge_request_label_events() -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.resourcelabelevents = create_autospec(
        ProjectMergeRequestResourceLabelEventManager
    )
    expected_event = create_autospec(ProjectMergeRequestResourceLabelEvent)
    mr.resourcelabelevents.list.return_value = [expected_event]

    events = GitLabApi.get_merge_request_label_events(mr)

    assert events == [expected_event]
    mr.resourcelabelevents.list.assert_called_once_with(get_all=True)


def test_get_merge_request_pipelines() -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.pipelines = create_autospec(ProjectMergeRequestPipelineManager)

    pipeline_1 = create_autospec(
        ProjectMergeRequestPipeline,
        id=1,
        created_at="2025-01-01T00:00:00Z",
    )
    pipeline_2 = create_autospec(
        ProjectMergeRequestPipeline,
        id=2,
        created_at="2025-01-02T00:00:00Z",
    )

    mr.pipelines.list.return_value = [pipeline_1, pipeline_2]

    pipelines = GitLabApi.get_merge_request_pipelines(mr)

    assert pipelines == [pipeline_2, pipeline_1]
    mr.pipelines.list.assert_called_once_with(iterator=True)


def test_get_repository_tree_as_git_cli_interface(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    project = mocked_gl.projects.get.return_value
    expected_result = [
        {
            "id": "a1e8f8d745cc87e3a9248358d9352bb7f9a0aeba",
            "name": "html",
            "type": "tree",
            "path": "files/html",
            "mode": "040000",
        }
    ]
    project.repository_tree.return_value = expected_result

    result = mocked_gitlab_api.get_repository_tree(
        ref="main",
        recursive=True,
    )

    assert result == expected_result
    project.repository_tree.assert_called_once_with(
        ref="main",
        recursive=True,
        pagination="keyset",
        per_page=100,
        get_all=True,
    )


def test_last_assignment() -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)

    note_1 = create_autospec(ProjectMergeRequestNote)
    note_1.system = True
    note_1.body = "assigned to @assignee_1"
    note_1.author = {"username": "author_1"}

    note_2 = create_autospec(ProjectMergeRequestNote)
    note_2.system = True
    note_2.body = "assigned to @assignee_2"
    note_2.author = {"username": "author_2"}

    mr.notes.list.return_value = [note_1, note_2]

    result = GitLabApi.last_assignment(mr)

    assert result == Assignment(author="author_1", assignee="assignee_1")

    mr.notes.list.assert_called_once_with(
        sort="desc",
        order_by="created_at",
        iterator=True,
    )


def test_get_personal_access_tokens(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    manager = mocked_gl.personal_access_tokens
    expected_pat = create_autospec(PersonalAccessToken)
    manager.list.return_value = [expected_pat]

    pats = mocked_gitlab_api.get_personal_access_tokens()

    assert pats == [expected_pat]
    manager.list.assert_called_once_with(get_all=True)


def test_get_directory_contents() -> None:
    project = create_autospec(Project)
    expected_result = {
        "dir1/hello1.yaml": b"id: 1",
        "dir1/dir2/hello2.yaml": b"id: 2",
    }
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w:gz") as tar:
        for name, content in expected_result.items():
            tarinfo = tarfile.TarInfo(name=f"prefix/{name}")
            tarinfo.size = len(content)
            tar.addfile(tarinfo, io.BytesIO(content))

    project.repository_archive.return_value = tar_bytes.getvalue()

    result = GitLabApi.get_directory_contents(project, ref="main", path="dir1")

    assert result == expected_result
    project.repository_archive.assert_called_once_with(
        format="tar.gz",
        sha="main",
        path="dir1",
    )


def test_get_file_as_git_cli_interface(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    expected_file = b"# README\nThis is a test file."
    project = mocked_gl.projects.get.return_value
    project_file_manager = create_autospec(ProjectFileManager)
    project.files = project_file_manager
    project_file_manager.raw.return_value = expected_file

    file = mocked_gitlab_api.get_file(path="/README.md", ref="main")

    assert file == expected_file
    project_file_manager.raw.assert_called_once_with(
        file_path="README.md",
        ref="main",
    )


def test_get_file_when_not_found(
    mocked_gitlab_api: GitLabApi,
    mocked_gl: Mock,
) -> None:
    project = mocked_gl.projects.get.return_value
    project_file_manager = create_autospec(ProjectFileManager)
    project.files = project_file_manager
    project_file_manager.raw.side_effect = GitlabGetError()

    file = mocked_gitlab_api.get_file(path="/README.md", ref="main")

    assert file is None
    project_file_manager.raw.assert_called_once_with(
        file_path="README.md",
        ref="main",
    )


def test_get_raw_file() -> None:
    expected_file = b"# README\nThis is a test file."
    project = create_autospec(Project)
    project_file_manager = create_autospec(ProjectFileManager)
    project.files = project_file_manager
    project_file_manager.raw.return_value = expected_file

    file = GitLabApi.get_raw_file(project=project, path="/README.md", ref="main")

    assert file == expected_file
    project_file_manager.raw.assert_called_once_with(
        file_path="README.md",
        ref="main",
    )
