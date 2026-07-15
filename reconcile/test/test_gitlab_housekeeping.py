from __future__ import annotations

from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import TYPE_CHECKING, Any
from unittest.mock import (
    MagicMock,
    Mock,
    create_autospec,
    patch,
)

import pytest
from gitlab import Gitlab
from gitlab.exceptions import (
    GitlabGetError,
    GitlabMRClosedError,
    GitlabMRRebaseError,
)
from gitlab.v4.objects import (
    Project,
    ProjectCommit,
    ProjectCommitManager,
    ProjectIssue,
    ProjectMergeRequest,
    ProjectMergeRequestNoteManager,
    ProjectMergeRequestPipeline,
    ProjectMergeRequestResourceLabelEvent,
)
from UnleashClient import UnleashClient

import reconcile.gitlab_housekeeping as gl_h
from reconcile.gitlab_housekeeping import RebaseStrategy
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

fixture = Fixtures("gitlab_housekeeping").get_anymarkup("api.yml")


def get_mock(path: str, **kwargs: Any) -> dict:
    path = path[1:]
    data = fixture.get("gitlab").get(path)
    return data


class TestGitLabHousekeeping:
    @staticmethod
    @patch.object(SecretReader, "read")
    @patch.object(Gitlab, "http_get")
    @patch.object(Gitlab, "http_post")
    def test_clean_pipelines_happy_path(
        http_post: MagicMock, http_get: MagicMock, _: MagicMock
    ) -> None:
        http_get.side_effect = get_mock
        now = datetime.now(tz=UTC)

        ten_minutes_ago = now - timedelta(minutes=10)
        two_hours_ago = now - timedelta(minutes=120)

        pipelines = [
            create_autospec(
                ProjectMergeRequestPipeline,
                id=46,
                iid=11,
                project_id=1,
                status="canceled",
                ref="new-pipeline",
                sha="dddd9c1e5c9015edee04321e423429d2f8924609",
                web_url="https://example.com/foo/bar/pipelines/46",
                created_at=two_hours_ago.strftime(DATE_FORMAT),
                updated_at=two_hours_ago.strftime(DATE_FORMAT),
            ),
            create_autospec(
                ProjectMergeRequestPipeline,
                id=47,
                iid=12,
                project_id=1,
                status="pending",
                ref="new-pipeline",
                sha="a91957a858320c0e17f3a0eca7cfacbff50ea29a",
                web_url="https://example.com/foo/bar/pipelines/47",
                created_at=two_hours_ago.strftime(DATE_FORMAT),
                updated_at=two_hours_ago.strftime(DATE_FORMAT),
            ),
            create_autospec(
                ProjectMergeRequestPipeline,
                id=48,
                iid=13,
                project_id=1,
                status="running",
                ref="new-pipeline",
                sha="eb94b618fb5865b26e80fdd8ae531b7a63ad851a",
                web_url="https://example.com/foo/bar/pipelines/48",
                created_at=ten_minutes_ago.strftime(DATE_FORMAT),
                updated_at=ten_minutes_ago.strftime(DATE_FORMAT),
            ),
        ]
        gl = GitLabApi({
            "url": "http://localhost",
            "sslVerify": False,
            "token": "token",
        })

        dry_run = False
        timeout = 60

        timeout_pipelines = gl_h.get_timed_out_pipelines(pipelines, timeout)
        gl_h.clean_pipelines(dry_run, gl, 1, timeout_pipelines)

        # Test if mock have this exact calls
        http_post.assert_called_once_with("/projects/1/pipelines/47/cancel")


def test_calculate_time_since_approval() -> None:
    one_hour_ago = (datetime.now(tz=UTC) - timedelta(minutes=60)).strftime(DATE_FORMAT)

    time_since_merge = gl_h._calculate_time_since_approval(one_hour_ago)

    assert round(time_since_merge) == 60


def test_is_rebase() -> None:
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
        page=1,
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
    mocker.patch("reconcile.gitlab_housekeeping.init_state", autospec=True)

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
def can_be_merged_merge_request() -> Mock:
    mr = create_autospec(ProjectMergeRequest)
    mr.merge_status = "can_be_merged"
    mr.draft = False
    mr.commits.return_value = [create_autospec(ProjectCommit)]
    mr.labels = ["lgtm"]
    mr.iid = 1
    mr.target_project_id = 3
    mr.squash = False
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
def success_merge_request_pipeline() -> ProjectMergeRequestPipeline:
    return create_autospec(
        ProjectMergeRequestPipeline,
        status="success",
    )


@pytest.mark.parametrize(
    ["project_squash_option", "merge_request_squash", "expected_squash"],
    [
        ("never", True, True),
        ("never", False, False),
        ("always", True, True),
        ("always", False, True),
        ("default_on", True, True),
        ("default_on", False, False),
        ("default_off", True, True),
        ("default_off", False, False),
    ],
)
def test_merge_merge_requests(
    state: Mock,
    project: Project,
    can_be_merged_merge_request: Mock,
    add_lgtm_merge_request_resource_label_event: ProjectMergeRequestResourceLabelEvent,
    success_merge_request_pipeline: ProjectMergeRequestPipeline,
    project_squash_option: str,
    merge_request_squash: bool,
    expected_squash: bool,
) -> None:
    mocked_gl = create_autospec(GitLabApi)
    project.squash_option = project_squash_option
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [
        add_lgtm_merge_request_resource_label_event
    ]
    mocked_gl.get_merge_request_pipelines.return_value = [
        success_merge_request_pipeline
    ]
    can_be_merged_merge_request.squash = merge_request_squash

    gl_h.merge_merge_requests(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[can_be_merged_merge_request],
        reload_toggle=gl_h.ReloadToggle(reload=False),
        merge_limit=1,
        rebase=False,
        app_sre_usernames=set(),
        state=state,
        pipeline_timeout=None,
        insist=True,
        wait_for_pipeline=False,
        users_allowed_to_label=None,
    )

    can_be_merged_merge_request.merge.assert_called_once_with(squash=expected_squash)


@pytest.fixture
def running_merge_request_pipeline() -> ProjectMergeRequestPipeline:
    return create_autospec(
        ProjectMergeRequestPipeline,
        status="running",
    )


def test_merge_merge_requests_with_retry(
    mocker: MockerFixture,
    state: Mock,
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
            state=state,
            pipeline_timeout=None,
            insist=True,
            wait_for_pipeline=True,
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


@pytest.fixture
def merge_request() -> Mock:
    mr = create_autospec(ProjectMergeRequest)
    commit = create_autospec(ProjectCommit)
    commit.id = "abc"
    commit.web_url = "a.b"
    mr.commits.return_value = iter([commit])
    mr.iid = 1
    mr.source_project_id = 4
    return mr


@pytest.fixture
def gitlab_api() -> Mock:
    gl = create_autospec(GitLabApi)
    project = create_autospec(Project)
    project.name = "b"
    project.path_with_namespace = "a/b"
    gl.project = project
    return gl


@pytest.fixture
def state() -> Mock:
    state = create_autospec(State)
    return state


class StatusMock:  # noqa: B903
    def __init__(self, name: str, status: str) -> None:
        self.name = name
        self.status = status


def test_verify_ondemend_tests_running(
    merge_request: Mock,
    gitlab_api: Mock,
    state: Mock,
) -> None:
    must_pass = ["pr-check", "e2e"]
    state.get.return_value = {"pr-check": "success"}
    gitlab_api.get_merge_request_pipelines.return_value = [
        create_autospec(
            ProjectMergeRequestPipeline,
            status="running",
        )
    ]

    assert not gl_h.verify_on_demand_tests(
        False, merge_request, must_pass, gitlab_api, state
    )
    state.get.assert_not_called()


def test_verify_ondemend_tests_state_fail(
    merge_request: Mock,
    gitlab_api: Mock,
    state: Mock,
) -> None:
    must_pass = ["pr-check", "e2e"]
    state.get.return_value = ["e2e"]
    gitlab_api.get_project_by_id.return_value.commits.get.return_value.statuses.list.return_value = [
        StatusMock("pr-check", "success")
    ]

    assert not gl_h.verify_on_demand_tests(
        False, merge_request, must_pass, gitlab_api, state
    )
    state.add.assert_not_called()


def test_verify_ondemend_tests_state_pass(
    merge_request: Mock,
    gitlab_api: Mock,
    state: Mock,
) -> None:
    must_pass = ["pr-check", "e2e"]
    state.get.return_value = []
    gitlab_api.get_project_by_id.return_value.commits.get.return_value.statuses.list.return_value = [
        StatusMock("pr-check", "success"),
        StatusMock("e2e", "success"),
    ]

    assert gl_h.verify_on_demand_tests(
        False, merge_request, must_pass, gitlab_api, state
    )
    state.add.assert_not_called()


def test_verify_ondemend_tests_fail(
    merge_request: Mock,
    gitlab_api: Mock,
    state: Mock,
) -> None:
    must_pass = ["pr-check", "e2e"]
    state.get.return_value = None
    gitlab_api.get_project_by_id.return_value.commits.get.return_value.statuses.list.return_value = [
        StatusMock("pr-check", "success")
    ]

    assert not gl_h.verify_on_demand_tests(
        False, merge_request, must_pass, gitlab_api, state
    )
    state.add.assert_called_once_with("a/b/1/abc", ["e2e"], force=True)


def test_verify_ondemend_tests_pass(
    merge_request: Mock,
    gitlab_api: Mock,
    state: Mock,
) -> None:
    must_pass = ["pr-check", "e2e"]
    state.get.return_value = ["e2e"]
    gitlab_api.get_project_by_id.return_value.commits.get.return_value.statuses.list.return_value = [
        StatusMock("pr-check", "success"),
        StatusMock("e2e", "success"),
    ]

    assert gl_h.verify_on_demand_tests(
        False, merge_request, must_pass, gitlab_api, state
    )
    state.add.assert_called_once_with("a/b/1/abc", [], force=True)


# --- rebase_merge_requests active-cap tests ---


def _call_rebase(
    mocker: MockerFixture,
    gitlab_api: Mock,
    state: Mock,
    merge_requests: list[Mock],
    rebase_limit: int,
    *,
    rebased_iids: set[int] | None = None,
    pipelines: dict[int, list] | None = None,
    dry_run: bool = False,
    pipeline_timeout: int | None = None,
    wait_for_pipeline: bool = False,
    strategy: RebaseStrategy = RebaseStrategy.ACTIVE_CAP,
) -> None:
    """Invoke rebase_merge_requests with standard patches.

    rebased_iids: iids for which is_rebased() returns True.
    pipelines: mapping of iid -> pipeline list for get_merge_request_pipelines().
    """
    rebased_set = rebased_iids or set()
    pipelines_map = pipelines or {}

    gitlab_api.get_merge_request_pipelines.side_effect = lambda mr: pipelines_map.get(
        mr.iid, []
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.get_merge_requests",
        return_value=[
            {"mr": mr, "error": any(label in gl_h.ERROR_LABELS for label in mr.labels)}
            for mr in merge_requests
        ],
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        side_effect=lambda mr, gl: mr.iid in rebased_set,
    )

    gl_h.rebase_merge_requests(
        dry_run=dry_run,
        gl=gitlab_api,
        rebase_limit=rebase_limit,
        state=state,
        pipeline_timeout=pipeline_timeout,
        wait_for_pipeline=wait_for_pipeline,
        strategy=strategy,
    )


def _make_rebase_mr(
    iid: int, project_id: int = 10, labels: list[str] | None = None
) -> Mock:
    """Create a minimal autospec MR for rebase tests."""
    mr = create_autospec(ProjectMergeRequest)
    mr.iid = iid
    mr.target_project_id = project_id
    mr.source_project_id = project_id
    mr.labels = labels or []
    return mr


def test_rebase_no_active_pipelines_full_budget(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """0 MRs have active pipelines, limit=2, 3 need rebase: exactly 2 rebased."""
    merge_requests = [_make_rebase_mr(i) for i in range(1, 4)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
    )

    assert merge_requests[0].rebase.call_count == 1
    assert merge_requests[1].rebase.call_count == 1
    assert merge_requests[2].rebase.call_count == 0


def test_rebase_active_pipelines_reduce_budget(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """1 MR rebased with running pipeline, limit=2: only 1 additional rebase."""
    running_pipeline = create_autospec(ProjectMergeRequestPipeline, status="running")
    merge_requests = [_make_rebase_mr(1), _make_rebase_mr(2), _make_rebase_mr(3)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        rebased_iids={1},
        pipelines={1: [running_pipeline]},
    )

    assert merge_requests[0].rebase.call_count == 0
    assert merge_requests[1].rebase.call_count == 1
    assert merge_requests[2].rebase.call_count == 0


def test_rebase_budget_exhausted(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """2 MRs with running pipelines, limit=2: 0 rebases."""
    running_pipeline = create_autospec(ProjectMergeRequestPipeline, status="running")
    pending_pipeline = create_autospec(ProjectMergeRequestPipeline, status="pending")
    merge_requests = [_make_rebase_mr(1), _make_rebase_mr(2), _make_rebase_mr(3)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        rebased_iids={1, 2},
        pipelines={1: [running_pipeline], 2: [pending_pipeline]},
    )

    assert merge_requests[0].rebase.call_count == 0
    assert merge_requests[1].rebase.call_count == 0
    assert merge_requests[2].rebase.call_count == 0


def test_rebase_all_already_rebased(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """All MRs pass is_rebased(): 0 rebases needed."""
    success_pipeline = create_autospec(ProjectMergeRequestPipeline, status="success")
    merge_requests = [_make_rebase_mr(1), _make_rebase_mr(2)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        rebased_iids={1, 2},
        pipelines={1: [success_pipeline], 2: [success_pipeline]},
    )

    for mr in merge_requests:
        assert mr.rebase.call_count == 0


def test_rebase_dry_run_no_rebases(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """In dry run, no actual rebases happen."""
    merge_requests = [_make_rebase_mr(i) for i in range(1, 3)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        dry_run=True,
    )

    for mr in merge_requests:
        assert mr.rebase.call_count == 0


def test_rebase_mixed_states(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """Mix of rebased-with-success, rebased-with-running, and not-rebased MRs.

    MR1: rebased, pipeline success -> consumes 1 from budget
    MR2: rebased, pipeline running -> consumes 1 from budget
    MR3: not rebased -> rebase candidate
    MR4: not rebased -> rebase candidate
    With limit=2, remaining_budget = 2 - 2 = 0, so no MRs get rebased.
    """
    success_pipeline = create_autospec(ProjectMergeRequestPipeline, status="success")
    running_pipeline = create_autospec(ProjectMergeRequestPipeline, status="running")
    merge_requests = [_make_rebase_mr(i) for i in range(1, 5)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        rebased_iids={1, 2},
        pipelines={1: [success_pipeline], 2: [running_pipeline]},
    )

    assert merge_requests[0].rebase.call_count == 0
    assert merge_requests[1].rebase.call_count == 0
    assert merge_requests[2].rebase.call_count == 0
    assert merge_requests[3].rebase.call_count == 0


def test_rebase_backward_compatible_zero_active(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """With 0 active pipelines, behaves identically to old per-run counter:
    rebase up to N MRs."""
    merge_requests = [_make_rebase_mr(i) for i in range(1, 6)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=3,
    )

    rebased_count = sum(mr.rebase.call_count for mr in merge_requests)
    assert rebased_count == 3
    assert merge_requests[0].rebase.call_count == 1
    assert merge_requests[1].rebase.call_count == 1
    assert merge_requests[2].rebase.call_count == 1
    assert merge_requests[3].rebase.call_count == 0
    assert merge_requests[4].rebase.call_count == 0


@pytest.mark.parametrize(
    ("limit", "expected_rebased"),
    [(1, 1), (3, 3), (5, 5), (10, 7)],
)
def test_rebase_differing_limits(
    mocker: MockerFixture,
    gitlab_api: Mock,
    state: Mock,
    limit: int,
    expected_rebased: int,
) -> None:
    """Verify different limit values produce different rebase counts."""
    merge_requests = [_make_rebase_mr(i) for i in range(1, 8)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=limit,
    )

    rebased_count = sum(mr.rebase.call_count for mr in merge_requests)
    assert rebased_count == expected_rebased, (
        f"limit={limit}: expected {expected_rebased} rebases, got {rebased_count}"
    )


def test_rebase_failure_does_not_consume_budget(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """A failed rebase doesn't consume a budget slot; subsequent MRs still get tried."""
    merge_requests = [_make_rebase_mr(1), _make_rebase_mr(2), _make_rebase_mr(3)]
    merge_requests[0].rebase.side_effect = GitlabMRRebaseError

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
    )

    assert merge_requests[0].rebase.call_count == 1
    assert merge_requests[1].rebase.call_count == 1
    assert merge_requests[2].rebase.call_count == 1


def test_rebase_over_committed_clamps_to_zero(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """When already_active > limit, remaining_budget clamps to 0."""
    running_pipeline = create_autospec(ProjectMergeRequestPipeline, status="running")
    pending_pipeline = create_autospec(ProjectMergeRequestPipeline, status="pending")
    merge_requests = [_make_rebase_mr(i) for i in range(1, 6)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        rebased_iids={1, 2, 3},
        pipelines={1: [running_pipeline], 2: [running_pipeline], 3: [pending_pipeline]},
    )

    assert merge_requests[3].rebase.call_count == 0
    assert merge_requests[4].rebase.call_count == 0


def test_rebase_mr_without_pipelines_not_counted_active(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """A rebased MR with no pipelines doesn't count toward already_active."""
    merge_requests = [_make_rebase_mr(1), _make_rebase_mr(2), _make_rebase_mr(3)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        rebased_iids={1},
    )

    assert merge_requests[0].rebase.call_count == 0
    assert merge_requests[1].rebase.call_count == 1
    assert merge_requests[2].rebase.call_count == 1


def test_rebase_limit_independent_per_repo(mocker: MockerFixture, state: Mock) -> None:
    """rebase_limit applies independently per repo.

    Simulate 3 repos with varying states, each processed via a separate
    rebase_merge_requests call (mirroring how run() iterates repos).
    With limit=2 each repo should get its own budget of 2.

    Repo A (project_id=10): 1 active pipeline + 3 need rebase -> 1 rebased
    Repo B (project_id=20): 0 active pipelines + 4 need rebase -> 2 rebased
    Repo C (project_id=30): 2 active pipelines + 2 need rebase -> 0 rebased
    """
    running_pipeline = create_autospec(ProjectMergeRequestPipeline, status="running")
    pending_pipeline = create_autospec(ProjectMergeRequestPipeline, status="pending")

    repo_a_merge_requests = [_make_rebase_mr(i, project_id=10) for i in range(1, 5)]
    repo_b_merge_requests = [_make_rebase_mr(i, project_id=20) for i in range(5, 9)]
    repo_c_merge_requests = [_make_rebase_mr(i, project_id=30) for i in range(9, 13)]

    repo_configs: list[tuple[list[Mock], set[int], dict[int, list]]] = [
        (repo_a_merge_requests, {1}, {1: [running_pipeline]}),
        (repo_b_merge_requests, set(), {}),
        (
            repo_c_merge_requests,
            {9, 10},
            {9: [running_pipeline], 10: [pending_pipeline]},
        ),
    ]
    for merge_requests, rebased_iids, pipelines in repo_configs:
        mocked_gl = create_autospec(GitLabApi)
        mocked_gl.project = create_autospec(Project)
        mocked_gl.project.name = "test-project"
        _call_rebase(
            mocker,
            mocked_gl,
            state,
            merge_requests,
            rebase_limit=2,
            rebased_iids=rebased_iids,
            pipelines=pipelines,
        )

    # Repo A: 1 active eats 1 slot -> 1 rebase
    assert repo_a_merge_requests[0].rebase.call_count == 0  # already rebased
    assert repo_a_merge_requests[1].rebase.call_count == 1
    assert repo_a_merge_requests[2].rebase.call_count == 0
    assert repo_a_merge_requests[3].rebase.call_count == 0

    # Repo B: 0 active -> full budget of 2
    assert repo_b_merge_requests[0].rebase.call_count == 1
    assert repo_b_merge_requests[1].rebase.call_count == 1
    assert repo_b_merge_requests[2].rebase.call_count == 0
    assert repo_b_merge_requests[3].rebase.call_count == 0

    # Repo C: 2 active exhaust budget -> 0 rebases
    assert repo_c_merge_requests[0].rebase.call_count == 0
    assert repo_c_merge_requests[1].rebase.call_count == 0
    assert repo_c_merge_requests[2].rebase.call_count == 0
    assert repo_c_merge_requests[3].rebase.call_count == 0


def test_rebase_stale_success_pipeline_does_not_block_rebase(
    mocker: MockerFixture, gitlab_api: Mock, state: Mock
) -> None:
    """A non-rebased MR whose previous pipeline succeeded should be eligible
    for rebase.  A stale SUCCESS pipeline is worthless — it ran against
    outdated code and should not permanently block the MR or consume budget."""
    success_pipeline = create_autospec(ProjectMergeRequestPipeline, status="success")
    merge_requests = [_make_rebase_mr(1), _make_rebase_mr(2)]

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        merge_requests,
        rebase_limit=2,
        rebased_iids=set(),
        pipelines={1: [success_pipeline]},
    )

    assert merge_requests[0].rebase.call_count == 1
    assert merge_requests[1].rebase.call_count == 1


@pytest.mark.parametrize(
    ("error_label", "strategy"),
    [
        ("merge-error", RebaseStrategy.ACTIVE_CAP),
        ("pipeline-error", RebaseStrategy.ACTIVE_CAP),
        ("rebase-error", RebaseStrategy.ACTIVE_CAP),
        ("merge-error", RebaseStrategy.OLD_BURST),
        ("pipeline-error", RebaseStrategy.OLD_BURST),
        ("rebase-error", RebaseStrategy.OLD_BURST),
    ],
)
def test_error_mr_skipped_in_rebase(
    mocker: MockerFixture,
    gitlab_api: Mock,
    state: Mock,
    error_label: str,
    strategy: RebaseStrategy,
) -> None:
    """An MR with an error label is never rebased, regardless of strategy."""
    error_mr = _make_rebase_mr(1, labels=[error_label])
    normal_mr = _make_rebase_mr(2)

    _call_rebase(
        mocker,
        gitlab_api,
        state,
        [error_mr, normal_mr],
        rebase_limit=2,
        strategy=strategy,
    )

    assert error_mr.rebase.call_count == 0
    assert normal_mr.rebase.call_count == 1


# --- get_rebase_strategy tests ---


@pytest.fixture
def unleash_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> Mock:
    """Set Unleash env vars and patch _get_unleash_api_client, returning the mock client."""
    monkeypatch.setenv("UNLEASH_API_URL", "http://fake")
    monkeypatch.setenv("UNLEASH_CLIENT_ACCESS_TOKEN", "fake")
    mock_client = create_autospec(UnleashClient)
    mocker.patch(
        "reconcile.utils.unleash.client._get_unleash_api_client",
        return_value=mock_client,
    )
    return mock_client


def test_get_rebase_strategy_no_unleash_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without UNLEASH_API_URL / UNLEASH_CLIENT_ACCESS_TOKEN, falls back to OLD_BURST."""
    monkeypatch.delenv("UNLEASH_API_URL", raising=False)
    monkeypatch.delenv("UNLEASH_CLIENT_ACCESS_TOKEN", raising=False)
    assert gl_h.get_rebase_strategy() == RebaseStrategy.OLD_BURST


def test_get_rebase_strategy_toggle_enabled_no_variant(
    unleash_client: Mock,
) -> None:
    """Toggle enabled but no variant configured → no payload → falls back to OLD_BURST."""
    unleash_client.get_variant.return_value = {"name": "disabled", "enabled": True}
    assert gl_h.get_rebase_strategy() == RebaseStrategy.OLD_BURST


def test_get_rebase_strategy_toggle_enabled_unknown_variant(
    unleash_client: Mock,
) -> None:
    """Toggle enabled with unrecognized variant value → logs warning, falls back to OLD_BURST."""
    unleash_client.get_variant.return_value = {
        "name": "bogus",
        "enabled": True,
        "payload": {"type": "string", "value": "bogus-strategy"},
    }
    assert gl_h.get_rebase_strategy() == RebaseStrategy.OLD_BURST


@pytest.mark.parametrize(
    ("variant_value", "expected_strategy"),
    [
        ("active-cap", RebaseStrategy.ACTIVE_CAP),
        ("old-burst", RebaseStrategy.OLD_BURST),
    ],
)
def test_get_rebase_strategy_toggle_enabled_valid_variant(
    unleash_client: Mock,
    variant_value: str,
    expected_strategy: RebaseStrategy,
) -> None:
    """Toggle enabled with a valid variant value → returns matching RebaseStrategy."""
    unleash_client.get_variant.return_value = {
        "name": variant_value,
        "enabled": True,
        "payload": {"type": "string", "value": variant_value},
    }
    assert gl_h.get_rebase_strategy() == expected_strategy


def test_merge_applies_merge_error_label_on_closed_error(
    state: Mock,
    project: Project,
    can_be_merged_merge_request: Mock,
    add_lgtm_merge_request_resource_label_event: ProjectMergeRequestResourceLabelEvent,
    success_merge_request_pipeline: ProjectMergeRequestPipeline,
) -> None:
    """GitlabMRClosedError on merge applies merge-error label silently (no note)."""
    mocked_gl = create_autospec(GitLabApi)
    project.squash_option = "never"
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [
        add_lgtm_merge_request_resource_label_event
    ]
    mocked_gl.get_merge_request_pipelines.return_value = [
        success_merge_request_pipeline
    ]
    can_be_merged_merge_request.merge.side_effect = GitlabMRClosedError("MR closed")

    gl_h.merge_merge_requests(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[can_be_merged_merge_request],
        reload_toggle=gl_h.ReloadToggle(reload=False),
        merge_limit=1,
        rebase=False,
        app_sre_usernames=set(),
        state=state,
        pipeline_timeout=None,
        insist=False,
        wait_for_pipeline=False,
        users_allowed_to_label=None,
    )

    mocked_gl.add_label_to_merge_request.assert_called_once_with(
        can_be_merged_merge_request, "merge-error"
    )


def test_merge_error_label_not_applied_in_dry_run(
    state: Mock,
    project: Project,
    can_be_merged_merge_request: Mock,
    add_lgtm_merge_request_resource_label_event: ProjectMergeRequestResourceLabelEvent,
    success_merge_request_pipeline: ProjectMergeRequestPipeline,
) -> None:
    """Dry-run mode does not attempt merge or apply any labels."""
    mocked_gl = create_autospec(GitLabApi)
    project.squash_option = "never"
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [
        add_lgtm_merge_request_resource_label_event
    ]
    mocked_gl.get_merge_request_pipelines.return_value = [
        success_merge_request_pipeline
    ]

    gl_h.merge_merge_requests(
        dry_run=True,
        gl=mocked_gl,
        project_merge_requests=[can_be_merged_merge_request],
        reload_toggle=gl_h.ReloadToggle(reload=False),
        merge_limit=1,
        rebase=False,
        app_sre_usernames=set(),
        state=state,
        pipeline_timeout=None,
        insist=False,
        wait_for_pipeline=False,
        users_allowed_to_label=None,
    )

    can_be_merged_merge_request.merge.assert_not_called()
    mocked_gl.add_label_to_merge_request.assert_not_called()


def _make_pipelines(statuses: list[str]) -> list[ProjectMergeRequestPipeline]:
    """Create a list of mock pipelines from status strings."""
    return [create_autospec(ProjectMergeRequestPipeline, status=s) for s in statuses]


def test_check_pipeline_health_all_failures() -> None:
    """Three consecutive failed pipelines marks MR as unhealthy."""
    pipelines = _make_pipelines(["failed", "failed", "failed"])
    assert gl_h.check_pipeline_health(pipelines) is False


def test_check_pipeline_health_all_canceled_is_healthy() -> None:
    """Canceled pipelines are not counted as failures."""
    pipelines = _make_pipelines(["canceled", "canceled", "canceled"])
    assert gl_h.check_pipeline_health(pipelines) is True


def test_check_pipeline_health_canceled_and_skipped_not_counted() -> None:
    """A mix of failed, canceled, and skipped is still considered healthy."""
    pipelines = _make_pipelines(["failed", "canceled", "skipped"])
    assert gl_h.check_pipeline_health(pipelines) is True


def test_check_pipeline_health_mixed_with_success() -> None:
    """A successful pipeline in the window breaks the failure streak."""
    pipelines = _make_pipelines(["failed", "failed", "success"])
    assert gl_h.check_pipeline_health(pipelines) is True


def test_check_pipeline_health_insufficient_history() -> None:
    """Fewer pipelines than the limit is treated as healthy."""
    pipelines = _make_pipelines(["failed", "failed"])
    assert gl_h.check_pipeline_health(pipelines) is True


def _make_healthcheck_mr(
    labels: list[str],
    merge_status: str = "can_be_merged",
    draft: bool = False,
    merge_error: str | None = None,
    detailed_merge_status: str | None = None,
) -> Mock:
    """Create a minimal mock MR for healthcheck tests."""
    mr = create_autospec(ProjectMergeRequest)
    mr.labels = labels
    mr.merge_status = merge_status
    mr.draft = draft
    mr.iid = 1
    mr.target_project_id = 1
    mr.merge_error = merge_error
    mr.detailed_merge_status = detailed_merge_status
    return mr


def test_pipeline_error_label_applied_on_consecutive_failures(
    project: Project,
) -> None:
    """Consecutive pipeline failures apply pipeline-error label."""
    mr = _make_healthcheck_mr(labels=["lgtm"])
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "failed",
        "failed",
        "failed",
    ])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
        consecutive_failure_limit=3,
    )

    mocked_gl.add_label_to_merge_request.assert_called_once_with(mr, "pipeline-error")
    mocked_gl.remove_label.assert_not_called()


def test_pipeline_error_label_auto_removed_on_recovery(
    project: Project,
) -> None:
    """A successful pipeline removes the pipeline-error label."""
    mr = _make_healthcheck_mr(labels=["lgtm", "pipeline-error"])
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "success",
        "failed",
        "failed",
    ])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
        consecutive_failure_limit=3,
    )

    mocked_gl.remove_label.assert_called_once_with(mr, "pipeline-error")
    mocked_gl.add_label_to_merge_request.assert_not_called()


def test_merge_error_label_not_removed_without_new_notes(
    project: Project,
) -> None:
    """merge-error stays when no notes have been posted since the label."""
    mr = _make_healthcheck_mr(labels=["lgtm", "merge-error"])
    label_event = create_autospec(ProjectMergeRequestResourceLabelEvent)
    label_event.action = "add"
    label_event.label = {"name": "merge-error"}
    label_event.created_at = "2025-06-01T12:00:00.0Z"

    note = Mock()
    note.created_at = "2025-06-01T11:00:00.0Z"
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)
    mr.notes.list.return_value = [note]

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [label_event]
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "success",
        "success",
        "success",
    ])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
        consecutive_failure_limit=3,
    )

    mocked_gl.remove_label.assert_not_called()
    mocked_gl.add_label_to_merge_request.assert_not_called()


def test_merge_error_label_removed_on_new_notes(
    project: Project,
) -> None:
    """merge-error is removed when new notes are posted after the label."""
    mr = _make_healthcheck_mr(labels=["lgtm", "merge-error"])
    label_event = create_autospec(ProjectMergeRequestResourceLabelEvent)
    label_event.action = "add"
    label_event.label = {"name": "merge-error"}
    label_event.created_at = "2025-06-01T12:00:00.0Z"

    note = Mock()
    note.created_at = "2025-06-01T13:00:00.0Z"
    mr.notes = create_autospec(ProjectMergeRequestNoteManager)
    mr.notes.list.return_value = [note]

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [label_event]
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "success",
        "success",
        "success",
    ])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
        consecutive_failure_limit=3,
    )

    mocked_gl.remove_label.assert_called_once_with(mr, "merge-error")
    mocked_gl.add_label_to_merge_request.assert_not_called()


def test_configurable_failure_limit(
    project: Project,
) -> None:
    """The consecutive failure threshold is respected when set to a custom value."""
    mr_3_failures = _make_healthcheck_mr(labels=["lgtm"])
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "failed",
        "failed",
        "failed",
        "success",
        "success",
    ])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr_3_failures],
        consecutive_failure_limit=5,
    )

    mocked_gl.add_label_to_merge_request.assert_not_called()

    mr_5_failures = _make_healthcheck_mr(labels=["lgtm"])
    mocked_gl.reset_mock()
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "failed",
        "failed",
        "failed",
        "failed",
        "failed",
    ])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr_5_failures],
        consecutive_failure_limit=5,
    )

    mocked_gl.add_label_to_merge_request.assert_called_once_with(
        mr_5_failures, "pipeline-error"
    )


def test_already_labeled_mr_with_ongoing_failures_no_api_calls(
    project: Project,
) -> None:
    """An MR that already has pipeline-error and is still failing
    should not trigger any label mutations on a subsequent healthcheck run."""
    mr = _make_healthcheck_mr(labels=["lgtm", "pipeline-error"])
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "failed",
        "failed",
        "failed",
    ])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
        consecutive_failure_limit=3,
    )

    mocked_gl.add_label_to_merge_request.assert_not_called()
    mocked_gl.remove_label.assert_not_called()


def test_healthcheck_skips_non_queue_eligible_mrs(project: Project) -> None:
    """MRs that fail is_good_to_merge are skipped by the healthcheck."""
    mrs: list[ProjectMergeRequest] = [
        _make_healthcheck_mr(labels=[]),
        _make_healthcheck_mr(labels=["lgtm", "do-not-merge/hold"]),
    ]
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines([
        "failed",
        "failed",
        "failed",
    ])
    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=mrs,
        consecutive_failure_limit=3,
    )
    mocked_gl.get_merge_request_pipelines.assert_not_called()
    mocked_gl.add_label_to_merge_request.assert_not_called()
    mocked_gl.remove_label.assert_not_called()


@pytest.mark.parametrize(
    "list_status",
    ["need_rebase", "ci_must_pass", "unchecked"],
)
def test_healthcheck_applies_rebase_error_on_merge_error_field(
    project: Project,
    list_status: str,
) -> None:
    """.get() confirms merge_error regardless of detailed_merge_status from .list()."""
    mr = _make_healthcheck_mr(
        labels=["lgtm"],
        detailed_merge_status=list_status,
    )
    fresh_mr = create_autospec(ProjectMergeRequest)
    fresh_mr.merge_error = (
        "Rebase failed: Rebase locally, resolve all conflicts, then push the branch."
    )

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request.return_value = fresh_mr

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
    )

    mocked_gl.get_merge_request.assert_called_once_with(mr.iid)
    mocked_gl.add_label_to_merge_request.assert_called_once_with(mr, "rebase-error")
    mocked_gl.get_merge_request_pipelines.assert_not_called()


@pytest.mark.parametrize(
    "resolved_status",
    ["mergeable", "ci_must_pass"],
)
def test_healthcheck_removes_rebase_error_when_merge_error_cleared(
    project: Project,
    resolved_status: str,
) -> None:
    """rebase-error is removed when .get() confirms merge_error is cleared."""
    mr = _make_healthcheck_mr(
        labels=["lgtm", "rebase-error"],
        detailed_merge_status=resolved_status,
    )
    fresh_mr = create_autospec(ProjectMergeRequest)
    fresh_mr.merge_error = None

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request.return_value = fresh_mr
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines(["success"])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
    )

    mocked_gl.get_merge_request.assert_called_once_with(mr.iid)
    mocked_gl.remove_label.assert_called_once_with(mr, "rebase-error")
    mocked_gl.add_label_to_merge_request.assert_not_called()


def test_healthcheck_skips_rebase_error_if_already_labeled(
    project: Project,
) -> None:
    """No duplicate add_label when rebase-error is already present."""
    mr = _make_healthcheck_mr(
        labels=["lgtm", "rebase-error"],
        detailed_merge_status="need_rebase",
    )
    fresh_mr = create_autospec(ProjectMergeRequest)
    fresh_mr.merge_error = "Rebase failed: conflict"

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request.return_value = fresh_mr
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines(["success"])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
    )

    mocked_gl.add_label_to_merge_request.assert_not_called()
    mocked_gl.remove_label.assert_not_called()


def test_healthcheck_no_rebase_error_when_resolved_despite_stale_detailed_status(
    project: Project,
) -> None:
    """detailed_merge_status='need_rebase' is stale but .get() shows merge_error cleared."""
    mr = _make_healthcheck_mr(
        labels=["lgtm"],
        detailed_merge_status="need_rebase",
    )
    fresh_mr = create_autospec(ProjectMergeRequest)
    fresh_mr.merge_error = None

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request.return_value = fresh_mr
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines(["success"])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
    )

    mocked_gl.get_merge_request.assert_called_once_with(mr.iid)
    mocked_gl.add_label_to_merge_request.assert_not_called()


def test_apply_omm_pending_rebase_error_applies_label(
    project: Project,
) -> None:
    """GitlabMRRebaseError at formation applies rebase-error label."""
    mr = create_autospec(ProjectMergeRequest)
    mr.iid = 100
    mr.target_project_id = 1
    mr.rebase.side_effect = GitlabMRRebaseError

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project

    gl_h.apply_omm_pending(dry_run=False, gl=mocked_gl, mrs=[mr])

    mocked_gl.add_label_to_merge_request.assert_any_call(mr, "omm-pending")
    mocked_gl.remove_label.assert_called_once_with(mr, "omm-pending")
    mocked_gl.add_label_to_merge_request.assert_any_call(mr, "rebase-error")


def test_healthcheck_ignores_non_rebase_merge_error(
    project: Project,
) -> None:
    """detailed_merge_status='need_rebase' but .get() merge_error is not a rebase failure."""
    mr = _make_healthcheck_mr(
        labels=["lgtm"],
        detailed_merge_status="need_rebase",
    )
    fresh_mr = create_autospec(ProjectMergeRequest)
    fresh_mr.merge_error = "Merge failed"

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request.return_value = fresh_mr
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines(["success"])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
    )

    mocked_gl.get_merge_request.assert_called_once_with(mr.iid)
    mocked_gl.add_label_to_merge_request.assert_not_called()


def test_healthcheck_preserves_rebase_error_on_api_failure(
    project: Project,
) -> None:
    """rebase-error label is preserved when fresh .get() raises GitlabGetError."""
    mr = _make_healthcheck_mr(
        labels=["lgtm", "rebase-error"],
        detailed_merge_status="need_rebase",
    )
    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.project.name = "test-project"
    mocked_gl.get_merge_request.side_effect = GitlabGetError("500 Server Error")
    mocked_gl.get_merge_request_pipelines.return_value = _make_pipelines(["success"])

    gl_h.run_error_healthcheck(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
    )

    mocked_gl.add_label_to_merge_request.assert_not_called()
    mocked_gl.remove_label.assert_not_called()
    mocked_gl.get_merge_request_pipelines.assert_called_once()


@pytest.mark.parametrize(
    "error_label",
    ["merge-error", "pipeline-error", "rebase-error"],
)
def test_error_mr_skipped_cleanly_with_no_side_effects(
    state: Mock,
    project: Project,
    can_be_merged_merge_request: Mock,
    add_lgtm_merge_request_resource_label_event: ProjectMergeRequestResourceLabelEvent,
    success_merge_request_pipeline: ProjectMergeRequestPipeline,
    error_label: str,
) -> None:
    """An MR with an error label should pass through the merge loop
    without any merge attempts, label mutations, or pipeline fetches."""
    can_be_merged_merge_request.labels = ["lgtm", error_label]
    mocked_gl = create_autospec(GitLabApi)
    project.squash_option = "never"
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [
        add_lgtm_merge_request_resource_label_event
    ]
    mocked_gl.get_merge_request_pipelines.return_value = [
        success_merge_request_pipeline
    ]

    gl_h.merge_merge_requests(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[can_be_merged_merge_request],
        reload_toggle=gl_h.ReloadToggle(reload=False),
        merge_limit=1,
        rebase=False,
        app_sre_usernames=set(),
        state=state,
        pipeline_timeout=None,
        insist=False,
        wait_for_pipeline=False,
        users_allowed_to_label=None,
    )

    can_be_merged_merge_request.merge.assert_not_called()
    mocked_gl.add_label_to_merge_request.assert_not_called()
    mocked_gl.remove_label.assert_not_called()


@pytest.mark.parametrize(
    "error_label",
    ["merge-error", "pipeline-error", "rebase-error"],
)
def test_error_labels_visible_in_queue(
    state: Mock,
    project: Project,
    add_lgtm_merge_request_resource_label_event: ProjectMergeRequestResourceLabelEvent,
    error_label: str,
) -> None:
    """MRs with error labels pass through preprocessing with error=True."""
    mr = create_autospec(ProjectMergeRequest)
    mr.merge_status = "can_be_merged"
    mr.draft = False
    mr.commits.return_value = [create_autospec(ProjectCommit)]
    mr.labels = ["lgtm", error_label]
    mr.iid = 1

    assert gl_h.is_good_to_merge(mr.labels) is True

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.project = project
    mocked_gl.get_merge_request_label_events.return_value = [
        add_lgtm_merge_request_resource_label_event
    ]

    results = gl_h.preprocess_merge_requests(
        dry_run=False,
        gl=mocked_gl,
        project_merge_requests=[mr],
        state=state,
        users_allowed_to_label=None,
    )

    assert len(results) == 1
    assert results[0]["mr"] is mr
    assert results[0]["error"] is True


class TestMergeErrorCycleEndToEnd:
    """End-to-end test for the silent merge-error label flow.

    Validates the full cycle:
      1. MR fails to merge (GitlabMRClosedError) → merge-error applied silently
      2. MR with merge-error is skipped by merge queue
      3. Human comments on MR
      4. Healthcheck detects new note → removes merge-error
      5. MR re-enters merge queue → fails again → merge-error re-applied
      6. Human comments again → healthcheck removes → merge succeeds
    """

    @pytest.fixture
    def gl(self, project: Project) -> Mock:
        mocked_gl = create_autospec(GitLabApi)
        project.squash_option = "never"
        project.id = "some-id"
        mocked_gl.project = project
        mocked_gl.user = Mock(username="bot-user")
        return mocked_gl

    @pytest.fixture
    def mr(self) -> Mock:
        mr = create_autospec(ProjectMergeRequest)
        mr.merge_status = "can_be_merged"
        mr.draft = False
        mr.commits.return_value = [create_autospec(ProjectCommit)]
        mr.labels = ["lgtm"]
        mr.iid = 42
        mr.target_project_id = 3
        mr.source_project_id = 3
        mr.squash = False
        mr.author = {"username": "developer"}
        mr.state = "opened"
        mr.notes = create_autospec(ProjectMergeRequestNoteManager)
        return mr

    @pytest.fixture
    def lgtm_label_event(self) -> ProjectMergeRequestResourceLabelEvent:
        event = create_autospec(ProjectMergeRequestResourceLabelEvent)
        event.action = "add"
        event.label = {"name": "lgtm"}
        event.user = {"username": "reviewer"}
        event.created_at = "2025-06-01T10:00:00.0Z"
        return event

    @pytest.fixture
    def success_pipeline(self) -> ProjectMergeRequestPipeline:
        return create_autospec(ProjectMergeRequestPipeline, status="success")

    def test_full_merge_error_cycle(
        self,
        state: Mock,
        gl: Mock,
        mr: Mock,
        lgtm_label_event: ProjectMergeRequestResourceLabelEvent,
        success_pipeline: ProjectMergeRequestPipeline,
    ) -> None:
        """Simulate the complete merge-error lifecycle through 6 steps."""
        gl.get_merge_request_label_events.return_value = [lgtm_label_event]
        gl.get_merge_request_pipelines.return_value = [success_pipeline]

        # --- Step 1: MR fails to merge → merge-error applied silently ---
        mr.merge.side_effect = GitlabMRClosedError("MR was closed")

        gl_h.merge_merge_requests(
            dry_run=False,
            gl=gl,
            project_merge_requests=[mr],
            reload_toggle=gl_h.ReloadToggle(reload=False),
            merge_limit=1,
            rebase=False,
            app_sre_usernames=set(),
            state=state,
            pipeline_timeout=None,
            insist=False,
            wait_for_pipeline=False,
            users_allowed_to_label=None,
        )

        gl.add_label_to_merge_request.assert_called_once_with(mr, "merge-error")
        gl.add_comment_to_merge_request.assert_not_called()
        gl.reset_mock()
        mr.merge.reset_mock()

        # --- Step 2: MR with merge-error is skipped by merge queue ---
        mr.labels = ["lgtm", "merge-error"]
        gl.get_merge_request_label_events.return_value = [lgtm_label_event]
        gl.get_merge_request_pipelines.return_value = [success_pipeline]

        gl_h.merge_merge_requests(
            dry_run=False,
            gl=gl,
            project_merge_requests=[mr],
            reload_toggle=gl_h.ReloadToggle(reload=False),
            merge_limit=1,
            rebase=False,
            app_sre_usernames=set(),
            state=state,
            pipeline_timeout=None,
            insist=False,
            wait_for_pipeline=False,
            users_allowed_to_label=None,
        )

        mr.merge.assert_not_called()
        gl.reset_mock()

        # --- Step 3 & 4: Human comments → healthcheck removes merge-error ---
        merge_error_label_event = create_autospec(ProjectMergeRequestResourceLabelEvent)
        merge_error_label_event.action = "add"
        merge_error_label_event.label = {"name": "merge-error"}
        merge_error_label_event.created_at = "2025-06-01T11:00:00.0Z"

        gl.get_merge_request_label_events.return_value = [merge_error_label_event]
        gl.get_merge_request_pipelines.return_value = [success_pipeline]

        human_note = Mock()
        human_note.created_at = "2025-06-01T12:00:00.0Z"
        human_note.system = False
        human_note.body = "I fixed the approval, please retry"
        human_note.author = {"username": "developer"}
        mr.notes.list.return_value = [human_note]

        gl_h.run_error_healthcheck(
            dry_run=False,
            gl=gl,
            project_merge_requests=[mr],
            consecutive_failure_limit=3,
        )

        gl.remove_label.assert_called_once_with(mr, "merge-error")
        gl.reset_mock()

        # --- Step 5: MR re-enters queue, fails again → merge-error re-applied ---
        mr.labels = ["lgtm"]
        mr.merge.reset_mock()
        mr.merge.side_effect = GitlabMRClosedError("MR was closed again")
        gl.get_merge_request_label_events.return_value = [lgtm_label_event]
        gl.get_merge_request_pipelines.return_value = [success_pipeline]

        gl_h.merge_merge_requests(
            dry_run=False,
            gl=gl,
            project_merge_requests=[mr],
            reload_toggle=gl_h.ReloadToggle(reload=False),
            merge_limit=1,
            rebase=False,
            app_sre_usernames=set(),
            state=state,
            pipeline_timeout=None,
            insist=False,
            wait_for_pipeline=False,
            users_allowed_to_label=None,
        )

        gl.add_label_to_merge_request.assert_called_once_with(mr, "merge-error")
        gl.add_comment_to_merge_request.assert_not_called()
        gl.reset_mock()

        # --- Step 6: Human comments again → healthcheck removes → merge succeeds ---
        mr.labels = ["lgtm", "merge-error"]

        merge_error_label_event_2 = create_autospec(
            ProjectMergeRequestResourceLabelEvent
        )
        merge_error_label_event_2.action = "add"
        merge_error_label_event_2.label = {"name": "merge-error"}
        merge_error_label_event_2.created_at = "2025-06-01T14:00:00.0Z"

        gl.get_merge_request_label_events.return_value = [merge_error_label_event_2]
        gl.get_merge_request_pipelines.return_value = [success_pipeline]

        human_note_2 = Mock()
        human_note_2.created_at = "2025-06-01T15:00:00.0Z"
        human_note_2.system = False
        human_note_2.body = "Fixed for real this time"
        human_note_2.author = {"username": "developer"}
        mr.notes.list.return_value = [human_note_2]

        gl_h.run_error_healthcheck(
            dry_run=False,
            gl=gl,
            project_merge_requests=[mr],
            consecutive_failure_limit=3,
        )

        gl.remove_label.assert_called_once_with(mr, "merge-error")
        gl.reset_mock()

        # MR re-enters queue and merges successfully
        mr.labels = ["lgtm"]
        mr.merge.reset_mock()
        mr.merge.side_effect = None
        gl.get_merge_request_label_events.return_value = [lgtm_label_event]
        gl.get_merge_request_pipelines.return_value = [success_pipeline]

        gl_h.merge_merge_requests(
            dry_run=False,
            gl=gl,
            project_merge_requests=[mr],
            reload_toggle=gl_h.ReloadToggle(reload=False),
            merge_limit=1,
            rebase=False,
            app_sre_usernames=set(),
            state=state,
            pipeline_timeout=None,
            insist=False,
            wait_for_pipeline=False,
            users_allowed_to_label=None,
        )

        mr.merge.assert_called_once_with(squash=False)
        gl.add_label_to_merge_request.assert_not_called()

    def test_no_loop_risk_bot_never_creates_notes(
        self,
        state: Mock,
        gl: Mock,
        mr: Mock,
        lgtm_label_event: ProjectMergeRequestResourceLabelEvent,
        success_pipeline: ProjectMergeRequestPipeline,
    ) -> None:
        """Verify the bot never creates notes during the merge-error flow,
        ensuring no infinite loop is possible."""
        gl.get_merge_request_label_events.return_value = [lgtm_label_event]
        gl.get_merge_request_pipelines.return_value = [success_pipeline]
        mr.merge.side_effect = GitlabMRClosedError("MR was closed")

        gl_h.merge_merge_requests(
            dry_run=False,
            gl=gl,
            project_merge_requests=[mr],
            reload_toggle=gl_h.ReloadToggle(reload=False),
            merge_limit=1,
            rebase=False,
            app_sre_usernames=set(),
            state=state,
            pipeline_timeout=None,
            insist=False,
            wait_for_pipeline=False,
            users_allowed_to_label=None,
        )

        gl.add_comment_to_merge_request.assert_not_called()
        mr.notes.create.assert_not_called()


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["lgtm", "tenant-foo", "tenant-bar"], {"tenant-foo", "tenant-bar"}),
        (["lgtm"], set()),
        ([], set()),
        (["tenant-a"], {"tenant-a"}),
        (["tenant-foo", "tenant-foo"], {"tenant-foo"}),
    ],
)
def test_get_tenant_labels(labels: list[str], expected: set[str]) -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.labels = labels
    assert gl_h.get_tenant_labels(mr) == expected


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["tenant-foo"], True),
        (["lgtm", "tenant-bar"], True),
        (["lgtm"], False),
        ([], False),
    ],
)
def test_is_eligible_for_optimistic_merge(labels: list[str], expected: bool) -> None:
    mr = create_autospec(ProjectMergeRequest)
    mr.labels = labels
    assert gl_h.is_eligible_for_optimistic_merge(mr) is expected


@pytest.mark.parametrize(
    ("mr_labels", "merged_labels", "expected"),
    [
        ({"tenant-foo"}, {"tenant-foo"}, True),
        ({"tenant-foo"}, {"tenant-bar"}, False),
        ({"tenant-foo", "tenant-bar"}, {"tenant-bar"}, True),
        (set(), {"tenant-foo"}, False),
        ({"tenant-foo"}, set(), False),
        (set(), set(), False),
    ],
)
def test_has_overlapping_labels(
    mr_labels: set[str], merged_labels: set[str], expected: bool
) -> None:
    assert gl_h.has_overlapping_labels(mr_labels, merged_labels) is expected


# --- multi-merge integration tests ---


def _make_merge_mr(
    iid: int,
    labels: list[str],
    *,
    target_project_id: int = 3,
    source_project_id: int = 3,
    squash: bool = False,
    author: str = "user",
    sha: str | None = None,
) -> Mock:
    mr = create_autospec(ProjectMergeRequest)
    mr.iid = iid
    mr.labels = labels
    mr.target_project_id = target_project_id
    mr.source_project_id = source_project_id
    mr.squash = squash
    mr.author = {"username": author}
    mr.merge_status = "can_be_merged"
    mr.draft = False
    mr.commits.return_value = [create_autospec(ProjectCommit)]
    mr.sha = sha if sha is not None else f"sha-{iid}"
    mr.target_branch = "master"
    return mr


def _make_merge_item(
    mr: Mock,
    *,
    error: bool = False,
) -> dict:
    return {
        "mr": mr,
        "label_priority": 0,
        "priority": "0 - approved",
        "approved_at": "2025-01-01T00:00:00.0Z",
        "approved_by": "user",
        "error": error,
    }


def _call_merge(
    mocker: MockerFixture,
    items: list[dict],
    *,
    rebase: bool = True,
    merge_limit: int = 10,
    insist: bool = False,
    wait_for_pipeline: bool = False,
    pipeline_timeout: int | None = None,
    pipelines_by_iid: dict[int, list] | None = None,
    rebased_iids: set[int] | None = None,
    dry_run: bool = False,
    multi_merge: bool = True,
) -> Mock:
    """Call merge_merge_requests with mocked preprocessing and is_rebased."""
    rebased_set = rebased_iids or set()
    pipelines_map = pipelines_by_iid or {}

    mocker.patch(
        "reconcile.gitlab_housekeeping.preprocess_merge_requests",
        return_value=items,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        side_effect=lambda mr, gl: mr.iid in rebased_set,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_group_lead",
        return_value=None,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[],
    )

    mocked_gl = create_autospec(GitLabApi)
    project = create_autospec(Project)
    project.id = "proj-1"
    project.name = "test-project"
    project.squash_option = "never"
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.side_effect = lambda mr: pipelines_map.get(
        mr.iid, []
    )

    state = create_autospec(State)

    gl_h.merge_merge_requests(
        dry_run=dry_run,
        gl=mocked_gl,
        project_merge_requests=[],
        reload_toggle=gl_h.ReloadToggle(reload=False),
        merge_limit=merge_limit,
        rebase=rebase,
        app_sre_usernames=set(),
        state=state,
        pipeline_timeout=pipeline_timeout,
        insist=insist,
        wait_for_pipeline=wait_for_pipeline,
        users_allowed_to_label=None,
        multi_merge=multi_merge,
    )

    return mocked_gl


def _success_pipeline(
    project_id: int = 1, sha: str = "pipeline-sha", source: str = "external"
) -> Mock:
    p = create_autospec(ProjectMergeRequestPipeline, status="success")
    p.project_id = project_id
    p.sha = sha
    p.source = source
    return p


def _running_pipeline(
    project_id: int = 1, sha: str = "pipeline-sha", source: str = "external"
) -> Mock:
    p = create_autospec(ProjectMergeRequestPipeline, status="running")
    p.project_id = project_id
    p.sha = sha
    p.source = source
    return p


def test_multi_merge_two_non_overlapping_tenants(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    mr3 = _make_merge_mr(12, ["approved", "tenant-baz"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2), _make_merge_item(mr3)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
            12: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()
    mr2.rebase.assert_called_once_with(skip_ci=True)
    mr3.merge.assert_not_called()
    mr3.rebase.assert_called_once_with(skip_ci=True)


def test_multi_merge_overlapping_tenants_serialized(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-foo"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()


def test_multi_merge_no_tenant_labels_falls_back_serial(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()


def test_multi_merge_three_mrs_partial_overlap(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    mr3 = _make_merge_mr(12, ["approved", "tenant-foo"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2), _make_merge_item(mr3)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
            12: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()
    mr3.merge.assert_not_called()


def test_multi_merge_respects_merge_limit(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    mr3 = _make_merge_mr(12, ["approved", "tenant-baz"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2), _make_merge_item(mr3)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        merge_limit=2,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
            12: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()
    mr3.merge.assert_not_called()


def test_multi_merge_skip_ci_rebase_failure_handled(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    mr3 = _make_merge_mr(12, ["approved", "tenant-baz"])
    mr2.rebase.side_effect = GitlabMRRebaseError("rebase conflict")
    items = [_make_merge_item(mr1), _make_merge_item(mr2), _make_merge_item(mr3)]

    mocked_gl = _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
            12: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()
    for call in mocked_gl.add_label_to_merge_request.call_args_list:
        assert call.args[1] != "merge-error"
    mocked_gl.remove_label.assert_called_once_with(mr2, "omm-pending")


def _setup_omm_group_mocks(
    mocker: MockerFixture,
    *,
    window_open: bool = True,
    ci_healthy: bool = True,
) -> None:
    """Shared setup for _process_omm_group tests."""
    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_max_interval",
        return_value=timedelta(minutes=10),
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping._is_omm_window_open",
        return_value=window_open,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping._check_post_merge_ci",
        return_value=ci_healthy,
    )


def _make_omm_gl(*, head_sha: str = "abc123") -> Mock:
    """Create a mocked GitLabApi for OMM group tests.

    ``head_sha`` controls what ``project.branches.get().commit["id"]``
    returns, allowing tests to simulate head-drift.
    """
    mocked_gl = create_autospec(GitLabApi)
    project = Mock()
    project.id = 1
    project.name = "test-project"
    project.squash_option = "never"
    branch_mock = Mock()
    branch_mock.commit = {"id": head_sha}
    project.branches.get.return_value = branch_mock
    mocked_gl.project = project
    return mocked_gl


@pytest.mark.parametrize(
    "error_label",
    ["pipeline-error", "merge-error", "rebase-error"],
)
def test_omm_group_ejects_error_labeled_mr(
    mocker: MockerFixture,
    error_label: str,
) -> None:
    """MRs with any error label are ejected from OMM groups without
    pipeline fetches or rebase attempts."""
    _setup_omm_group_mocks(mocker)
    mocker.patch("reconcile.gitlab_housekeeping.clear_omm_group")

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = "abc123"
    lead.squash_commit_sha = None
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending", error_label])

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mocked_gl.remove_label.assert_called_once_with(mr, "omm-pending")
    mocked_gl.get_merge_request_pipelines.assert_not_called()
    mr.merge.assert_not_called()
    mr.rebase.assert_not_called()


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_merge_rejected_applies_merge_error(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """When a pending MR's merge raises GitlabMRClosedError during OMM
    group processing, merge-error is applied and omm-pending is removed."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])
    mr.merge.side_effect = GitlabMRClosedError("MR was closed")

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [_success_pipeline()]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_called_once()
    mocked_gl.add_label_to_merge_request.assert_called_once_with(mr, "merge-error")
    mocked_gl.remove_label.assert_called_once_with(mr, "omm-pending")


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_head_drift_invalidates_group(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """When target branch HEAD differs from the lead's resolved SHA the
    group is invalidated immediately."""
    _setup_omm_group_mocks(mocker)
    clear_mock = mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mocked_gl = _make_omm_gl(head_sha="different-sha")
    mocked_gl.project.repository_compare.return_value = {"commits": ["x"]}

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    clear_mock.assert_called_once_with(False, mocked_gl, lead=lead)


def test_omm_group_lead_missing_merge_commit_sha(
    mocker: MockerFixture,
) -> None:
    """When both merge_commit_sha and squash_commit_sha are None,
    return 0 without crashing and leave the group intact for the next loop."""
    _setup_omm_group_mocks(mocker)
    clear_mock = mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = None
    lead.squash_commit_sha = None
    lead.target_branch = "master"
    lead.iid = 99999

    mocked_gl = _make_omm_gl(head_sha="some-sha")

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    clear_mock.assert_not_called()
    mocked_gl.project.branches.get.assert_not_called()
    mocked_gl.project.repository_compare.assert_not_called()


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_head_advanced_but_reachable_continues(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """When HEAD advanced because a pending member merged (lead commit
    still reachable), the group stays valid and processing continues."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="advanced-sha")
    mocked_gl.project.repository_compare.return_value = {"commits": []}
    mocked_gl.get_merge_request_pipelines.return_value = [_success_pipeline()]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 1
    mr.merge.assert_called_once()
    mocked_gl.project.repository_compare.assert_called_once_with(
        "advanced-sha", "abc123"
    )


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_skip_ci_rebase_on_success_not_rebased(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """A pending MR with SUCCESS pipeline that is not rebased (HEAD moved)
    gets a skip_ci rebase and keeps the group active."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=False,
    )
    clear_mock = mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [_success_pipeline()]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.rebase.assert_called_once_with(skip_ci=True)
    mr.merge.assert_not_called()
    clear_mock.assert_not_called()


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_skip_ci_rebase_failure_ejects_member(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """When skip_ci rebase fails during group processing, the MR is
    ejected (omm-pending removed) and counted as a rejection."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=False,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])
    mr.rebase.side_effect = GitlabMRRebaseError("rebase conflict")

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [_success_pipeline()]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_not_called()
    mocked_gl.remove_label.assert_called_once_with(mr, "omm-pending")


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_merge_limit_enforced(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """When merge_limit is reached during OMM group processing the group
    is cleared and processing stops."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    clear_mock = mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr1 = _make_merge_mr(10, ["approved", "tenant-foo", "omm-pending"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr1, mr2],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [_success_pipeline()]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
        merge_limit=1,
    )

    assert merges == 1
    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()
    clear_mock.assert_called_once()


def test_multi_merge_running_pipeline_skipped_after_first_merge(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        wait_for_pipeline=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_running_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()


def test_multi_merge_insist_only_before_first_merge(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    items = [_make_merge_item(mr1)]

    mocker.patch(
        "reconcile.gitlab_housekeeping.preprocess_merge_requests",
        return_value=items,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_group_lead",
        return_value=None,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[],
    )

    mocked_gl = create_autospec(GitLabApi)
    project = create_autospec(Project)
    project.id = "proj-1"
    project.name = "test-project"
    project.squash_option = "never"
    mocked_gl.project = project
    mocked_gl.get_merge_request_pipelines.return_value = [_running_pipeline()]

    with pytest.raises(gl_h.InsistOnPipelineError):
        gl_h.merge_merge_requests(
            dry_run=False,
            gl=mocked_gl,
            project_merge_requests=[],
            reload_toggle=gl_h.ReloadToggle(reload=False),
            merge_limit=10,
            rebase=True,
            app_sre_usernames=set(),
            state=create_autospec(State),
            pipeline_timeout=None,
            insist=True,
            wait_for_pipeline=True,
            users_allowed_to_label=None,
            multi_merge=True,
        )

    mr1.merge.assert_not_called()


def test_multi_merge_multi_tenant_mr_naturally_serialized(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-foo", "tenant-bar", "tenant-baz"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()


def test_multi_merge_error_mr_skipped(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo", "merge-error"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    items = [_make_merge_item(mr1, error=True), _make_merge_item(mr2)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={11},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
        },
    )

    mr1.merge.assert_not_called()
    mr2.merge.assert_called_once()
    mr2.rebase.assert_not_called()


def test_multi_merge_batch_size_histogram_observed(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    mr3 = _make_merge_mr(12, ["approved", "tenant-baz"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2), _make_merge_item(mr3)]

    observe_mock = mocker.patch.object(
        gl_h.merge_batch_size_histogram, "labels", return_value=Mock()
    )

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
            12: [_success_pipeline()],
        },
    )

    observe_mock.assert_called_once_with(project_id="proj-1")
    observe_mock.return_value.observe.assert_called_once_with(1)


def test_multi_merge_rebase_false_unchanged(
    mocker: MockerFixture,
) -> None:
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    mr3 = _make_merge_mr(12, ["approved"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2), _make_merge_item(mr3)]

    _call_merge(
        mocker,
        items,
        rebase=False,
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
            12: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_called_once()
    mr3.merge.assert_called_once()
    mr1.rebase.assert_not_called()
    mr2.rebase.assert_not_called()
    mr3.rebase.assert_not_called()


def test_multi_merge_disabled_single_merge_on_rebase(
    mocker: MockerFixture,
) -> None:
    """When multi_merge=False and rebase=True, only the first MR merges."""
    mr1 = _make_merge_mr(10, ["approved", "tenant-foo"])
    mr2 = _make_merge_mr(11, ["approved", "tenant-bar"])
    items = [_make_merge_item(mr1), _make_merge_item(mr2)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        multi_merge=False,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_success_pipeline()],
            11: [_success_pipeline()],
        },
    )

    mr1.merge.assert_called_once()
    mr2.merge.assert_not_called()
    mr2.rebase.assert_not_called()


# --- OMM skipped pipeline handling tests ---


def _skipped_pipeline(
    project_id: int = 1, sha: str = "pipeline-sha", source: str = "external"
) -> Mock:
    p = create_autospec(ProjectMergeRequestPipeline, status="skipped")
    p.project_id = project_id
    p.sha = sha
    p.source = source
    return p


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_skipped_pipeline_filtered_merges_on_pre_rebase_success(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """After skip-ci rebase, GitLab creates a 'skipped' pipeline. The code
    should filter it out and use the pre-rebase SUCCESS pipeline to merge."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [
        _skipped_pipeline(),
        _success_pipeline(),
    ]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 1
    mr.merge.assert_called_once()


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_all_skipped_pipelines_rebased_stays_active(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """When all pipelines are 'skipped' and the MR is rebased, the group
    should stay active (any_active=True) rather than triggering adaptive-close."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    clear_mock = mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [_skipped_pipeline()]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_not_called()
    clear_mock.assert_not_called()


def _canceled_pipeline(
    project_id: int = 1, sha: str = "pipeline-sha", source: str = "external"
) -> Mock:
    p = create_autospec(ProjectMergeRequestPipeline, status="canceled")
    p.project_id = project_id
    p.sha = sha
    p.source = source
    return p


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_unhandled_status_rebased_stays_active(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """An unexpected pipeline status (e.g. 'canceled') on a rebased MR
    should keep the group active rather than triggering adaptive-close."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    clear_mock = mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    mr = _make_merge_mr(11, ["approved", "tenant-bar", "omm-pending"])

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [_canceled_pipeline()]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_not_called()
    clear_mock.assert_not_called()


# --- Fork pipeline SHA filtering in OMM group ---


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_fork_pipeline_post_rebase_filtered_merges(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """After skip-ci rebase, fork pipelines matching the new MR SHA are
    filtered out.  The pre-rebase fork SUCCESS pipeline (old SHA) should
    drive the merge decision."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    fork_id = 99
    new_sha = "rebased-sha"
    old_sha = "pre-rebase-sha"

    mr = _make_merge_mr(
        11,
        ["approved", "tenant-bar", "omm-pending"],
        source_project_id=fork_id,
        sha=new_sha,
    )

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [
        _running_pipeline(project_id=fork_id, sha=new_sha, source="push"),
        _success_pipeline(project_id=fork_id, sha=old_sha),
    ]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 1
    mr.merge.assert_called_once()


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_fork_pipeline_not_rebased_triggers_skip_ci(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """A non-rebased fork MR whose current-HEAD fork pipeline is SUCCESS
    should trigger a skip-ci rebase.  The fork SHA filter must NOT discard
    the pipeline when the MR is not yet rebased."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=False,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    fork_id = 99
    current_sha = "current-head-sha"

    mr = _make_merge_mr(
        11,
        ["approved", "tenant-bar", "omm-pending"],
        source_project_id=fork_id,
        sha=current_sha,
    )

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [
        _success_pipeline(project_id=fork_id, sha=current_sha),
    ]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_not_called()
    mr.rebase.assert_called_once_with(skip_ci=True)


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_fork_pipeline_running_old_sha_waits(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """A rebased fork MR whose real CI (old SHA) is still RUNNING should
    wait.  The running fork pipeline is kept because its SHA differs from
    mr.sha."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=True,
    )
    clear_mock = mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    fork_id = 99
    new_sha = "rebased-sha"
    old_sha = "pre-rebase-sha"

    mr = _make_merge_mr(
        11,
        ["approved", "tenant-bar", "omm-pending"],
        source_project_id=fork_id,
        sha=new_sha,
    )

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [
        _running_pipeline(project_id=fork_id, sha=old_sha),
    ]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_not_called()
    mr.rebase.assert_not_called()
    clear_mock.assert_not_called()


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_fork_push_pipeline_filtered_when_not_rebased(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """Defect A: a non-rebased fork MR has a push pipeline at mr.sha (noise
    from fork CI firing on the new commit) alongside the real external SUCCESS
    pipeline.  The push pipeline must be filtered regardless of rebased state,
    leaving the external SUCCESS to drive skip-ci rebase."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=False,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    fork_id = 99
    current_sha = "current-head-sha"

    mr = _make_merge_mr(
        11,
        ["approved", "tenant-bar", "omm-pending"],
        source_project_id=fork_id,
        sha=current_sha,
    )

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [
        _running_pipeline(project_id=fork_id, sha=current_sha, source="push"),
        _success_pipeline(project_id=fork_id, sha=current_sha, source="external"),
    ]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_not_called()
    mr.rebase.assert_called_once_with(skip_ci=True)


@pytest.mark.parametrize(
    "merge_sha, squash_sha",
    [("abc123", None), (None, "abc123")],
    ids=["merge-commit", "squash-commit"],
)
def test_omm_group_fork_external_pipeline_preserved_at_current_sha(
    mocker: MockerFixture,
    merge_sha: str | None,
    squash_sha: str | None,
) -> None:
    """Regression guard: a fork MR whose only pipeline at mr.sha has
    source='external' (the real Jenkins/Konflux CI) must NOT be filtered.
    The external pipeline should drive the merge or rebase decision normally."""
    _setup_omm_group_mocks(mocker)
    mocker.patch(
        "reconcile.gitlab_housekeeping.is_rebased",
        return_value=False,
    )
    mocker.patch(
        "reconcile.gitlab_housekeeping.clear_omm_group",
    )

    lead = create_autospec(ProjectMergeRequest)
    lead.merge_commit_sha = merge_sha
    lead.squash_commit_sha = squash_sha
    lead.target_branch = "master"

    fork_id = 99
    current_sha = "current-head-sha"

    mr = _make_merge_mr(
        11,
        ["approved", "tenant-bar", "omm-pending"],
        source_project_id=fork_id,
        sha=current_sha,
    )

    mocker.patch(
        "reconcile.gitlab_housekeeping.get_omm_pending_mrs",
        return_value=[mr],
    )

    mocked_gl = _make_omm_gl(head_sha="abc123")
    mocked_gl.get_merge_request_pipelines.return_value = [
        _success_pipeline(project_id=fork_id, sha=current_sha, source="external"),
    ]

    merges = gl_h._process_omm_group(
        dry_run=False,
        gl=mocked_gl,
        lead=lead,
        app_sre_usernames=set(),
    )

    assert merges == 0
    mr.merge.assert_not_called()
    mr.rebase.assert_called_once_with(skip_ci=True)


# --- Skipped pipeline filtering in serial merge and _form_omm_group ---


def test_serial_merge_skipped_pipeline_filtered_merges_on_success(
    mocker: MockerFixture,
) -> None:
    """After an OMM skip-ci rebase, the SKIPPED pipeline lands at pipelines[0].
    The serial merge path should filter it out and merge on the SUCCESS pipeline."""
    mr = _make_merge_mr(10, ["approved", "tenant-foo"])
    items = [_make_merge_item(mr)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_skipped_pipeline(), _success_pipeline()],
        },
    )

    mr.merge.assert_called_once()


def test_serial_merge_all_skipped_pipelines_skips_mr(
    mocker: MockerFixture,
) -> None:
    """When all pipelines are SKIPPED, the serial merge path should skip the MR
    (no merge, no crash) rather than blocking on the SKIPPED status."""
    mr = _make_merge_mr(10, ["approved", "tenant-foo"])
    items = [_make_merge_item(mr)]

    _call_merge(
        mocker,
        items,
        rebase=True,
        rebased_iids={10},
        pipelines_by_iid={
            10: [_skipped_pipeline(), _skipped_pipeline()],
        },
    )

    mr.merge.assert_not_called()


def test_form_omm_group_skipped_pipeline_filtered_includes_candidate(
    mocker: MockerFixture,
) -> None:
    """_form_omm_group should filter SKIPPED pipelines and include an MR
    whose underlying pipeline is SUCCESS."""
    mr = _make_merge_mr(10, ["approved", "tenant-foo"])
    items = [_make_merge_item(mr)]

    mocked_gl = create_autospec(GitLabApi)
    mocked_gl.get_merge_request_pipelines.return_value = [
        _skipped_pipeline(),
        _success_pipeline(),
    ]

    candidates = gl_h._form_omm_group(mocked_gl, items, set())

    assert candidates == [mr]
