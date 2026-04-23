from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Any
from unittest.mock import (
    MagicMock,
    Mock,
    create_autospec,
    patch,
)

import gitlab
import pytest
from gitlab import Gitlab
from gitlab.v4.objects import (
    Project,
    ProjectCommit,
    ProjectCommitManager,
    ProjectIssue,
    ProjectMergeRequest,
    ProjectMergeRequestPipeline,
    ProjectMergeRequestResourceLabelEvent,
)
from pytest_mock import MockerFixture

import reconcile.gitlab_housekeeping as gl_h
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State

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


# --- rebase_merge_requests per-repo concurrency cap tests ---


def _make_pipeline(status: str) -> Mock:
    return create_autospec(ProjectMergeRequestPipeline, status=status)


def _make_mr(
    iid: int,
    *,
    is_rebased: bool = False,
    pipeline_status: str | None = None,
) -> Mock:
    """Create a mock MR.

    is_rebased: whether is_rebased() should return True for this MR.
    pipeline_status: if set, get_merge_request_pipelines returns a pipeline
        with this status; otherwise returns [].
    """
    mr = create_autospec(ProjectMergeRequest)
    mr.iid = iid
    mr.target_project_id = 10
    mr.source_project_id = 10
    mr._test_is_rebased = is_rebased
    mr._test_pipelines = [_make_pipeline(pipeline_status)] if pipeline_status else []
    return mr


class TestRebaseMergeRequests:
    """Tests for rebase_merge_requests() with per-repo concurrency cap.

    rebase_limit controls the max number of MRs with active (running/pending)
    pipelines at any time, not the number of rebases per invocation.
    """

    @staticmethod
    def _call(
        mocker: MockerFixture,
        merge_requests: list[Mock],
        rebase_limit: int,
        *,
        dry_run: bool = False,
        pipeline_timeout: int | None = None,
        wait_for_pipeline: bool = False,
    ) -> None:
        """Invoke rebase_merge_requests with mocked internals."""
        mocked_gl = create_autospec(GitLabApi)
        mocked_project = create_autospec(Project)
        mocked_project.name = "test-project"
        mocked_gl.project = mocked_project
        mocked_gl.get_merge_request_pipelines.side_effect = lambda mr: (
            mr._test_pipelines
        )
        mocked_state = create_autospec(State)

        mocker.patch(
            "reconcile.gitlab_housekeeping.get_merge_requests",
            return_value=[{"mr": mr} for mr in merge_requests],
        )
        mocker.patch(
            "reconcile.gitlab_housekeeping.is_rebased",
            side_effect=lambda mr, gl: mr._test_is_rebased,
        )

        gl_h.rebase_merge_requests(
            dry_run=dry_run,
            gl=mocked_gl,
            rebase_limit=rebase_limit,
            state=mocked_state,
            pipeline_timeout=pipeline_timeout,
            wait_for_pipeline=wait_for_pipeline,
        )

    def test_no_active_pipelines_full_budget(self, mocker: MockerFixture) -> None:
        """0 MRs have active pipelines, limit=2, 3 need rebase: exactly 2 rebased."""
        mrs = [_make_mr(1), _make_mr(2), _make_mr(3)]

        self._call(mocker, mrs, rebase_limit=2)

        assert mrs[0].rebase.call_count == 1
        assert mrs[1].rebase.call_count == 1
        assert mrs[2].rebase.call_count == 0

    def test_active_pipelines_reduce_budget(self, mocker: MockerFixture) -> None:
        """1 MR rebased with running pipeline, limit=2: only 1 additional rebase."""
        mr_active = _make_mr(1, is_rebased=True, pipeline_status="running")
        mr_needs_a = _make_mr(2)
        mr_needs_b = _make_mr(3)
        mrs = [mr_active, mr_needs_a, mr_needs_b]

        self._call(mocker, mrs, rebase_limit=2)

        assert mr_active.rebase.call_count == 0
        assert mr_needs_a.rebase.call_count == 1
        assert mr_needs_b.rebase.call_count == 0

    def test_budget_exhausted(self, mocker: MockerFixture) -> None:
        """2 MRs with running pipelines, limit=2: 0 rebases."""
        mr_a = _make_mr(1, is_rebased=True, pipeline_status="running")
        mr_b = _make_mr(2, is_rebased=True, pipeline_status="pending")
        mr_c = _make_mr(3)
        mrs = [mr_a, mr_b, mr_c]

        self._call(mocker, mrs, rebase_limit=2)

        assert mr_c.rebase.call_count == 0

    def test_all_already_rebased(self, mocker: MockerFixture) -> None:
        """All MRs pass is_rebased(): 0 rebases needed."""
        mrs = [
            _make_mr(1, is_rebased=True, pipeline_status="success"),
            _make_mr(2, is_rebased=True, pipeline_status="success"),
        ]

        self._call(mocker, mrs, rebase_limit=2)

        for mr in mrs:
            assert mr.rebase.call_count == 0

    def test_dry_run_no_rebases(self, mocker: MockerFixture) -> None:
        """In dry run, no actual rebases happen."""
        mrs = [_make_mr(1), _make_mr(2)]

        self._call(mocker, mrs, rebase_limit=2, dry_run=True)

        for mr in mrs:
            assert mr.rebase.call_count == 0

    def test_mixed_states(self, mocker: MockerFixture) -> None:
        """Mix of rebased-with-success, rebased-with-running, and not-rebased MRs.

        MR1: rebased, pipeline success (not active) -> doesn't consume budget
        MR2: rebased, pipeline running (active) -> consumes 1 from budget
        MR3: not rebased -> rebase candidate
        MR4: not rebased -> rebase candidate
        With limit=2, remaining_budget = 2 - 1 = 1, so only MR3 gets rebased.
        """
        mrs = [
            _make_mr(1, is_rebased=True, pipeline_status="success"),
            _make_mr(2, is_rebased=True, pipeline_status="running"),
            _make_mr(3),
            _make_mr(4),
        ]

        self._call(mocker, mrs, rebase_limit=2)

        assert mrs[0].rebase.call_count == 0
        assert mrs[1].rebase.call_count == 0
        assert mrs[2].rebase.call_count == 1
        assert mrs[3].rebase.call_count == 0

    def test_backward_compatible_zero_active(self, mocker: MockerFixture) -> None:
        """With 0 active pipelines, behaves identically to old per-run counter:
        rebase up to N MRs."""
        mrs = [_make_mr(i) for i in range(1, 6)]

        self._call(mocker, mrs, rebase_limit=3)

        rebased_count = sum(mr.rebase.call_count for mr in mrs)
        assert rebased_count == 3
        assert mrs[0].rebase.call_count == 1
        assert mrs[1].rebase.call_count == 1
        assert mrs[2].rebase.call_count == 1
        assert mrs[3].rebase.call_count == 0
        assert mrs[4].rebase.call_count == 0

    def test_differing_limits(self, mocker: MockerFixture) -> None:
        """Verify different limit values produce different rebase counts."""
        for limit, expected_rebased in [(1, 1), (3, 3), (5, 5), (10, 7)]:
            mrs = [_make_mr(i) for i in range(1, 8)]

            self._call(mocker, mrs, rebase_limit=limit)

            rebased_count = sum(mr.rebase.call_count for mr in mrs)
            assert rebased_count == expected_rebased, (
                f"limit={limit}: expected {expected_rebased} rebases, got {rebased_count}"
            )

    def test_rebase_failure_does_not_consume_budget(
        self, mocker: MockerFixture
    ) -> None:
        """A failed rebase doesn't consume a budget slot; subsequent MRs still get tried."""
        mr_fail = _make_mr(1)
        mr_fail.rebase.side_effect = gitlab.exceptions.GitlabMRRebaseError
        mr_ok_a = _make_mr(2)
        mr_ok_b = _make_mr(3)
        mrs = [mr_fail, mr_ok_a, mr_ok_b]

        self._call(mocker, mrs, rebase_limit=2)

        assert mr_fail.rebase.call_count == 1
        assert mr_ok_a.rebase.call_count == 1
        assert mr_ok_b.rebase.call_count == 1

    def test_over_committed_clamps_to_zero(self, mocker: MockerFixture) -> None:
        """When already_active > limit, remaining_budget clamps to 0."""
        mrs = [
            _make_mr(1, is_rebased=True, pipeline_status="running"),
            _make_mr(2, is_rebased=True, pipeline_status="running"),
            _make_mr(3, is_rebased=True, pipeline_status="pending"),
            _make_mr(4),
            _make_mr(5),
        ]

        self._call(mocker, mrs, rebase_limit=2)

        assert mrs[3].rebase.call_count == 0
        assert mrs[4].rebase.call_count == 0

    def test_rebased_mr_without_pipelines_not_counted_active(
        self, mocker: MockerFixture
    ) -> None:
        """A rebased MR with no pipelines doesn't count toward already_active."""
        mr_rebased_no_pipeline = _make_mr(1, is_rebased=True)
        mr_needs_a = _make_mr(2)
        mr_needs_b = _make_mr(3)
        mrs = [mr_rebased_no_pipeline, mr_needs_a, mr_needs_b]

        self._call(mocker, mrs, rebase_limit=2)

        assert mr_rebased_no_pipeline.rebase.call_count == 0
        assert mr_needs_a.rebase.call_count == 1
        assert mr_needs_b.rebase.call_count == 1
