from __future__ import annotations

from unittest.mock import Mock, create_autospec

from gitlab.exceptions import GitlabCreateError
from gitlab.v4.objects import (
    Project,
    ProjectMergeRequest,
    ProjectMergeRequestPipeline,
)

from reconcile.gitlab_housekeeping.fork_pipelines import (
    NO_CI_CONFIG_STATE_VALUE,
    trigger_fork_pipelines,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.state import State

TARGET_PROJECT_ID = 13582
FORK_PROJECT_ID = 43874


def _project() -> Project:
    project = create_autospec(Project)
    project.id = TARGET_PROJECT_ID
    project.name = "service/app-interface"
    project.path_with_namespace = "service/app-interface"
    return project


def _gl(project: Project) -> GitLabApi:
    gl = create_autospec(GitLabApi)
    gl.project = project
    return gl


def _mr(*, source_project_id: int, iid: int, sha: str) -> ProjectMergeRequest:
    mr = create_autospec(ProjectMergeRequest)
    mr.source_project_id = source_project_id
    mr.iid = iid
    mr.sha = sha
    return mr


def _pipeline(sha: str) -> ProjectMergeRequestPipeline:
    return create_autospec(ProjectMergeRequestPipeline, sha=sha)


def _state() -> Mock:
    state = create_autospec(State)
    state.get.return_value = None
    return state


def test_skips_non_fork_merge_requests() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    mr = _mr(source_project_id=TARGET_PROJECT_ID, iid=1, sha="abc123")

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache={},
    )

    gl.get_merge_request_pipelines.assert_not_called()
    gl.create_merge_request_pipeline.assert_not_called()


def test_skips_fork_mr_with_pipeline_for_current_sha() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    mr = _mr(source_project_id=FORK_PROJECT_ID, iid=2, sha="abc123")
    gl.get_merge_request_pipelines.return_value = [_pipeline("abc123")]

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache={},
    )

    gl.create_merge_request_pipeline.assert_not_called()


def test_triggers_fork_mr_with_no_pipeline_for_current_sha() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    mr = _mr(source_project_id=FORK_PROJECT_ID, iid=3, sha="new-sha")
    # only has a pipeline for an older, already-superseded commit
    gl.get_merge_request_pipelines.return_value = [_pipeline("old-sha")]

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache={},
    )

    gl.create_merge_request_pipeline.assert_called_once_with(mr)


def test_dry_run_does_not_trigger() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    mr = _mr(source_project_id=FORK_PROJECT_ID, iid=4, sha="new-sha")
    gl.get_merge_request_pipelines.return_value = []

    trigger_fork_pipelines(
        dry_run=True,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache={},
    )

    gl.create_merge_request_pipeline.assert_not_called()


def test_uses_and_refreshes_pipeline_cache() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    mr = _mr(source_project_id=FORK_PROJECT_ID, iid=5, sha="new-sha")
    pipeline_cache = {5: [_pipeline("old-sha")]}

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache=pipeline_cache,
    )

    # served from the cache, no extra API call needed to decide to trigger
    gl.get_merge_request_pipelines.assert_not_called()
    gl.create_merge_request_pipeline.assert_called_once_with(mr)
    # cache entry dropped so a later lookup this run re-fetches and sees it
    assert 5 not in pipeline_cache


def test_missing_gitlab_ci_yml_does_not_block_other_merge_requests() -> None:
    """Most fork branches have no .gitlab-ci.yml, which GitLab reports as a
    GitlabCreateError rather than a silent no-op. One MR hitting that must
    not stop the rest of the project's MRs from being processed."""
    project = _project()
    gl = _gl(project)
    state = _state()
    mr_without_ci_config = _mr(source_project_id=FORK_PROJECT_ID, iid=6, sha="sha-a")
    mr_with_ci_config = _mr(source_project_id=FORK_PROJECT_ID, iid=7, sha="sha-b")
    gl.get_merge_request_pipelines.return_value = []
    gl.create_merge_request_pipeline.side_effect = [
        GitlabCreateError("Missing .gitlab-ci.yml file"),
        None,
    ]

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr_without_ci_config, mr_with_ci_config],
        state=state,
        pipeline_cache={},
    )

    assert gl.create_merge_request_pipeline.call_count == 2
    gl.create_merge_request_pipeline.assert_any_call(mr_without_ci_config)
    gl.create_merge_request_pipeline.assert_any_call(mr_with_ci_config)


def test_missing_gitlab_ci_yml_is_remembered_in_state() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    mr = _mr(source_project_id=FORK_PROJECT_ID, iid=8, sha="sha-a")
    gl.get_merge_request_pipelines.return_value = []
    gl.create_merge_request_pipeline.side_effect = GitlabCreateError(
        "Missing .gitlab-ci.yml file"
    )

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache={},
    )

    state.add.assert_called_once_with(
        "service/app-interface/8/sha-a",
        NO_CI_CONFIG_STATE_VALUE,
        force=True,
    )


def test_does_not_retry_a_sha_already_known_to_have_no_ci_config() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    state.get.return_value = NO_CI_CONFIG_STATE_VALUE
    mr = _mr(source_project_id=FORK_PROJECT_ID, iid=9, sha="sha-a")

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache={},
    )

    gl.get_merge_request_pipelines.assert_not_called()
    gl.create_merge_request_pipeline.assert_not_called()


def test_new_commit_is_retried_even_if_a_previous_sha_had_no_ci_config() -> None:
    project = _project()
    gl = _gl(project)
    state = _state()
    # only the *old* sha was ever marked as having no CI config
    state.get.side_effect = lambda key, default=None: (
        NO_CI_CONFIG_STATE_VALUE if key.endswith("/sha-old") else default
    )
    mr = _mr(source_project_id=FORK_PROJECT_ID, iid=10, sha="sha-new")
    gl.get_merge_request_pipelines.return_value = []

    trigger_fork_pipelines(
        dry_run=False,
        gl=gl,
        project_merge_requests=[mr],
        state=state,
        pipeline_cache={},
    )

    gl.create_merge_request_pipeline.assert_called_once_with(mr)
