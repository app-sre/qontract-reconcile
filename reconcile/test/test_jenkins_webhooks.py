from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest

from reconcile import jenkins_webhooks, jenkins_webhooks_cleaner

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


PROJECT_URL = "https://gitlab.example.com/group/project"
JOB_URL = "https://jenkins.example.com/project/job"
HOOK_IDS = count(1)


def make_hook(
    url: str,
    *,
    mr: bool = False,
    push: bool = False,
    note: bool = False,
    **settings: Any,
) -> Mock:
    attrs = {
        "url": url,
        "push_events": push,
        "merge_requests_events": mr,
        "note_events": note,
        "issues_events": False,
        "tag_push_events": False,
        "pipeline_events": False,
        "push_events_branch_filter": None,
        "branch_filter_strategy": "wildcard",
        "enable_ssl_verification": True,
        "token_present": False,
        "signing_token_present": False,
        "duo_flow_callback_enabled": False,
        "custom_webhook_template": None,
        "custom_headers": [],
        "url_variables": [],
        "name": None,
        "description": None,
        "disabled_until": None,
    }
    attrs.update(settings)
    hook_id = next(HOOK_IDS)
    hook = Mock(
        id=hook_id,
        url=url,
        merge_requests_events=mr,
        push_events=push,
        note_events=note,
        attributes={
            field: value
            for field, value in attrs.items()
            if field not in {"custom_headers", "url_variables"}
        },
    )
    hook.manager.get.return_value = Mock(id=hook_id, url=url, attributes=attrs)
    return hook


@pytest.mark.parametrize(
    ("current_hooks", "expected_additions"),
    [
        ([make_hook(JOB_URL + "/", mr=True)], []),
        ([], [{"job_url": JOB_URL, "trigger": ["mr"]}]),
    ],
)
def test_get_hooks_to_add_deduplicates_desired_hooks(
    current_hooks: list[Mock], expected_additions: list[dict], mocker: MockerFixture
) -> None:
    gl = mocker.Mock()
    gl.get_project_hooks.return_value = current_hooks
    desired_hook = {"job_url": JOB_URL, "trigger": ["mr"]}
    desired_state = {PROJECT_URL: [desired_hook, desired_hook.copy()]}

    result = jenkins_webhooks.get_hooks_to_add(desired_state, gl)

    assert result == {PROJECT_URL: expected_additions}
    assert desired_state[PROJECT_URL] == [desired_hook, desired_hook]


def test_get_hooks_to_add_distinguishes_triggers(mocker: MockerFixture) -> None:
    gl = mocker.Mock()
    gl.get_project_hooks.return_value = [make_hook(JOB_URL, mr=True)]
    desired = {"job_url": JOB_URL, "trigger": ["push"]}

    result = jenkins_webhooks.get_hooks_to_add({PROJECT_URL: [desired]}, gl)

    assert result == {PROJECT_URL: [desired]}


@pytest.mark.parametrize("dry_run", [True, False])
def test_jenkins_webhooks_skips_creation_when_listing_fails(
    dry_run: bool, mocker: MockerFixture
) -> None:
    mocker.patch("reconcile.jenkins_webhooks.queries.get_secret_reader_settings")
    mocker.patch("reconcile.jenkins_webhooks.SecretReader")
    jjb = mocker.patch("reconcile.jenkins_webhooks.init_jjb").return_value
    jjb.get_job_webhooks_data.return_value = {
        PROJECT_URL: [{"job_url": JOB_URL, "trigger": ["mr"]}]
    }
    gl = mocker.patch("reconcile.jenkins_webhooks.get_gitlab_api").return_value
    gl.get_project_hooks.side_effect = RuntimeError("GitLab unavailable")

    jenkins_webhooks.run(dry_run=dry_run)

    gl.create_project_hook.assert_not_called()


@pytest.fixture
def cleaner_gl(mocker: MockerFixture) -> tuple[Mock, Mock]:
    mocker.patch("reconcile.jenkins_webhooks_cleaner.queries.get_gitlab_instance")
    mocker.patch("reconcile.jenkins_webhooks_cleaner.get_app_interface_vault_settings")
    mocker.patch("reconcile.jenkins_webhooks_cleaner.create_secret_reader")
    mocker.patch(
        "reconcile.jenkins_webhooks_cleaner.get_jenkins_instances",
        return_value=[Mock(server_url="https://jenkins.example.com")],
    )
    mocker.patch(
        "reconcile.jenkins_webhooks_cleaner.queries.get_jenkins_instances_previous_urls",
        return_value=["https://old-jenkins.example.com"],
    )
    repos_query = mocker.patch(
        "reconcile.jenkins_webhooks_cleaner.queries.get_repos",
        return_value=[PROJECT_URL],
    )
    gl = mocker.patch("reconcile.jenkins_webhooks_cleaner.GitLabApi").return_value
    gl.server = "https://gitlab.example.com"
    return gl, repos_query


@pytest.mark.parametrize("dry_run", [True, False])
def test_jenkins_webhooks_cleaner_removes_only_identical_managed_hooks(
    dry_run: bool, cleaner_gl: tuple[Mock, Mock]
) -> None:
    gl, _ = cleaner_gl
    first = make_hook(JOB_URL, mr=True, note=True)
    duplicate = make_hook(JOB_URL + "/", mr=True, note=True)
    different_trigger = make_hook(JOB_URL, push=True)
    tag_hook = make_hook(JOB_URL + "/", tag_push_events=True)
    pipeline_hook = make_hook(JOB_URL, pipeline_events=True)
    filtered_push = make_hook(JOB_URL, push=True, push_events_branch_filter="main")
    different_branch_strategy = make_hook(
        JOB_URL, push=True, branch_filter_strategy="all_branches"
    )
    custom_header = make_hook(
        JOB_URL, mr=True, note=True, custom_headers=[{"key": "X-Test"}]
    )
    custom_variable = make_hook(
        JOB_URL, mr=True, note=True, url_variables=[{"key": "environment"}]
    )
    other_url = make_hook("https://receiver.example.com/hook", push=True)
    other_url_duplicate = make_hook("https://receiver.example.com/hook", push=True)
    old_url = make_hook("https://old-jenkins.example.com/project/job", push=True)
    old_unmanaged = make_hook("https://old-jenkins.example.com/manual", push=True)
    gl.get_project_hooks.return_value = [
        first,
        duplicate,
        different_trigger,
        tag_hook,
        pipeline_hook,
        filtered_push,
        different_branch_strategy,
        custom_header,
        custom_variable,
        other_url,
        other_url_duplicate,
        old_url,
        old_unmanaged,
    ]

    jenkins_webhooks_cleaner.run(dry_run=dry_run)

    for hook in (
        first,
        different_trigger,
        tag_hook,
        pipeline_hook,
        filtered_push,
        different_branch_strategy,
        custom_header,
        custom_variable,
        other_url,
        other_url_duplicate,
        old_unmanaged,
    ):
        hook.delete.assert_not_called()
    assert duplicate.delete.call_count == (0 if dry_run else 1)
    assert old_url.delete.call_count == (0 if dry_run else 1)


def test_jenkins_webhooks_cleaner_continues_after_failed_delete(
    cleaner_gl: tuple[Mock, Mock], caplog: pytest.LogCaptureFixture
) -> None:
    gl, repos_query = cleaner_gl
    other_repo = PROJECT_URL + "-other"
    repos_query.return_value = [PROJECT_URL, other_repo]
    first = make_hook(JOB_URL, mr=True, note=True)
    successful_duplicate = make_hook(JOB_URL + "/", mr=True, note=True)
    failed = make_hook("https://old-jenkins.example.com/project/fail", push=True)
    failed.delete.side_effect = RuntimeError("503 Service Unavailable")
    later = make_hook("https://old-jenkins.example.com/project/later", push=True)
    other_repo_hook = make_hook(
        "https://old-jenkins.example.com/project/other", push=True
    )
    gl.get_project_hooks.side_effect = [
        [first, successful_duplicate, failed, later],
        [other_repo_hook],
    ]

    jenkins_webhooks_cleaner.run(dry_run=False)

    successful_duplicate.delete.assert_called_once()
    failed.delete.assert_called_once()
    later.delete.assert_not_called()
    other_repo_hook.delete.assert_called_once()
    assert any(
        PROJECT_URL in record.getMessage()
        and str(failed.id) in record.getMessage()
        and "Failed deleting" in record.getMessage()
        for record in caplog.records
    )
