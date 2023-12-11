from datetime import (
    datetime,
    timedelta,
)
from unittest.mock import (
    create_autospec,
    patch,
)

import pytest
from gitlab import Gitlab
from gitlab.v4.objects import (
    Project,
    ProjectCommit,
    ProjectCommitManager,
    ProjectIssue,
    ProjectMergeRequest,
    ProjectMergeRequestResourceLabelEvent,
)
from pytest_mock import MockerFixture

import reconcile.gitlab_housekeeping as gl_h
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import SecretReader

DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

fixture = Fixtures("gitlab_housekeeping").get_anymarkup("api.yml")


def get_mock(path, query_data=None, streamed=False, raw=False, **kwargs):
    path = path[1:]
    data = fixture.get("gitlab").get(path)
    return data


class TestGitLabHousekeeping:
    @staticmethod
    @patch.object(SecretReader, "read")
    @patch.object(Gitlab, "http_get")
    @patch.object(Gitlab, "http_post")
    def test_clean_pipelines_happy_path(http_post, http_get, secret_read):
        http_get.side_effect = get_mock
        now = datetime.utcnow()

        ten_minutes_ago = now - timedelta(minutes=10)
        two_hours_ago = now - timedelta(minutes=120)

        pipelines = [
            {
                "id": 46,
                "iid": 11,
                "project_id": 1,
                "status": "canceled",
                "ref": "new-pipeline",
                "sha": "dddd9c1e5c9015edee04321e423429d2f8924609",
                "web_url": "https://example.com/foo/bar/pipelines/46",
                "created_at": two_hours_ago.strftime(DATE_FORMAT),
                "updated_at": two_hours_ago.strftime(DATE_FORMAT),
            },
            {
                "id": 47,
                "iid": 12,
                "project_id": 1,
                "status": "pending",
                "ref": "new-pipeline",
                "sha": "a91957a858320c0e17f3a0eca7cfacbff50ea29a",
                "web_url": "https://example.com/foo/bar/pipelines/47",
                "created_at": two_hours_ago.strftime(DATE_FORMAT),
                "updated_at": two_hours_ago.strftime(DATE_FORMAT),
            },
            {
                "id": 48,
                "iid": 13,
                "project_id": 1,
                "status": "running",
                "ref": "new-pipeline",
                "sha": "eb94b618fb5865b26e80fdd8ae531b7a63ad851a",
                "web_url": "https://example.com/foo/bar/pipelines/48",
                "created_at": ten_minutes_ago.strftime(DATE_FORMAT),
                "updated_at": ten_minutes_ago.strftime(DATE_FORMAT),
            },
        ]
        instance = {"url": "http://localhost", "sslVerify": False, "token": "token"}

        dry_run = False
        timeout = 60

        timeout_pipelines = gl_h.get_timed_out_pipelines(pipelines, timeout)
        gl_h.clean_pipelines(dry_run, instance, "1", "", timeout_pipelines)

        # Test if mock have this exact calls
        http_post.assert_called_once_with("/projects/1/pipelines/47/cancel")


def test_calculate_time_since_approval():
    one_hour_ago = (datetime.utcnow() - timedelta(minutes=60)).strftime(DATE_FORMAT)

    time_since_merge = gl_h._calculate_time_since_approval(one_hour_ago)

    assert round(time_since_merge) == 60


def test_is_rebase():
    expected_ref = "master"
    mr = create_autospec(ProjectMergeRequest)
    mr.target_branch = expected_ref
    expected_sha = "some-sha"
    mr.sha = expected_sha

    mocked_gitlab_api = create_autospec(GitLabApi)
    mocked_gitlab_api.project = create_autospec(Project)
    mocked_gitlab_api.project.commits = create_autospec(ProjectCommitManager)
    mocked_commit = create_autospec(ProjectCommit)
    expected_head = "some-id"
    mocked_commit.id = expected_head
    mocked_gitlab_api.project.commits.list.return_value = [mocked_commit]

    mocked_gitlab_api.project.repository_compare.return_value = {"commits": []}

    result = gl_h.is_rebased(mr, mocked_gitlab_api)

    assert result is True
    mocked_gitlab_api.project.commits.list.assert_called_once_with(
        ref_name=expected_ref,
        per_page=1,
    )
    mocked_gitlab_api.project.repository_compare.assert_called_once_with(
        expected_sha,
        expected_head,
    )


@pytest.fixture
def repo_gitlab_housekeeping() -> dict:
    return {
        "url": "https://gitlab.com/org/repo",
        "housekeeping": {
            "enabled": True,
            "rebase": False,
            "enable_closing": True,
        },
    }


def test_dry_run(
    mocker: MockerFixture,
    repo_gitlab_housekeeping: dict,
) -> None:
    mocked_queries = mocker.patch("reconcile.gitlab_housekeeping.queries")
    mocked_queries.get_repos_gitlab_housekeeping.return_value = [
        repo_gitlab_housekeeping,
    ]
    mocked_gitlab_api = mocker.patch(
        "reconcile.gitlab_housekeeping.GitLabApi", autospec=True
    ).return_value.__enter__.return_value

    gl_h.run(True, False)

    mocked_gitlab_api.get_issues.assert_called_once_with(state="opened")
    mocked_gitlab_api.get_merge_requests.assert_called_once_with(state="opened")
    mocked_gitlab_api.get_app_sre_group_users.assert_called_once_with()


@pytest.fixture
def project() -> Project:
    project = create_autospec(Project)
    project.id = "some-id"
    project.name = "some-name"
    return project


@pytest.fixture
def can_be_merged_merge_request() -> ProjectMergeRequest:
    mr = create_autospec(ProjectMergeRequest)
    mr.merge_status = "can_be_merged"
    mr.work_in_progress = False
    mr.commits.return_value = [create_autospec(ProjectCommit)]
    mr.labels = ["lgtm"]
    mr.iid = 1
    mr.target_project_id = 3
    mr.author = {"username": "user"}
    return mr


@pytest.fixture
def add_lgtm_merge_request_resource_label_event() -> (
    ProjectMergeRequestResourceLabelEvent
):
    event = create_autospec(ProjectMergeRequestResourceLabelEvent)
    event.action = "add"
    event.label = {"name": "lgtm"}
    event.user = {"username": "user"}
    event.created_at = "2023-01-01T00:00:00.0Z"
    return event


@pytest.fixture
def success_merge_request_pipeline() -> dict:
    return {
        "status": "success",
    }


def test_merge_merge_requests(
    project: Project,
    can_be_merged_merge_request: ProjectMergeRequest,
    add_lgtm_merge_request_resource_label_event: ProjectMergeRequestResourceLabelEvent,
    success_merge_request_pipeline: dict,
) -> None:
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [
        add_lgtm_merge_request_resource_label_event
    ]
    mocked_gl.get_merge_request_pipelines.return_value = [
        success_merge_request_pipeline
    ]

    gl_h.merge_merge_requests(
        False,
        mocked_gl,
        [can_be_merged_merge_request],
        gl_h.ReloadToggle(reload=False),
        1,
        False,
        app_sre_usernames=set(),
        pipeline_timeout=None,
        insist=True,
        wait_for_pipeline=False,
        gl_instance=None,
        gl_settings=None,
        users_allowed_to_label=None,
    )

    can_be_merged_merge_request.merge.assert_called_once()


@pytest.fixture
def running_merge_request_pipeline() -> dict:
    return {
        "status": "running",
    }


def test_merge_merge_requests_with_retry(
    mocker: MockerFixture,
    project: Project,
    can_be_merged_merge_request: ProjectMergeRequest,
    add_lgtm_merge_request_resource_label_event: ProjectMergeRequestResourceLabelEvent,
    running_merge_request_pipeline: dict,
) -> None:
    mocker.patch("time.sleep")
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_requests.return_value = [can_be_merged_merge_request]
    mocked_gl.get_merge_request_label_events.return_value = [
        add_lgtm_merge_request_resource_label_event
    ]
    mocked_gl.get_merge_request_pipelines.return_value = [
        running_merge_request_pipeline
    ]

    with pytest.raises(gl_h.InsistOnPipelineError) as e:
        gl_h.merge_merge_requests(
            False,
            mocked_gl,
            [can_be_merged_merge_request],
            gl_h.ReloadToggle(reload=False),
            1,
            False,
            app_sre_usernames=set(),
            pipeline_timeout=None,
            insist=True,
            wait_for_pipeline=True,
            gl_instance=None,
            gl_settings=None,
            users_allowed_to_label=None,
        )

    assert (
        f"Pipelines for merge request in project 'some-name' have not completed yet: {can_be_merged_merge_request.iid}"
        == str(e.value)
    )

    assert mocked_gl.get_merge_requests.call_count == 9


def test_close_item_with_enable_closing(
    mocker: MockerFixture,
    project: Project,
) -> None:
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_logging = mocker.patch("reconcile.gitlab_housekeeping.logging")
    mocked_issue = create_autospec(ProjectIssue)
    mocked_issue.attributes = {"iid": 1}

    gl_h.close_item(False, mocked_gl, True, "issue", mocked_issue)

    mocked_gl.close.assert_called_once_with(mocked_issue)
    mocked_logging.info.assert_called_once_with([
        "close_item",
        project.name,
        "issue",
        1,
    ])
    mocked_logging.debug.assert_not_called()


def test_close_item_without_enable_closing(
    mocker: MockerFixture,
    project: Project,
) -> None:
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_logging = mocker.patch("reconcile.gitlab_housekeeping.logging")
    mocked_issue = create_autospec(ProjectIssue)
    mocked_issue.attributes = {"iid": 1}

    gl_h.close_item(False, mocked_gl, False, "issue", mocked_issue)

    mocked_gl.close.assert_not_called()
    mocked_logging.debug.assert_called_once_with([
        "'enable_closing' is not enabled to close item",
        project.name,
        "issue",
        1,
    ])
    mocked_logging.info.assert_not_called()
