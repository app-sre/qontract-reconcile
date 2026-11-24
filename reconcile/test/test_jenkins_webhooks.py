from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from reconcile import jenkins_webhooks, jenkins_webhooks_cleaner

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


PROJECT_URL = "https://gitlab.example.com/group/project"
JOB_URL = "https://jenkins.example.com/project/job"


def make_hook(
    url: str, *, mr: bool = False, push: bool = False, note: bool = False
) -> Mock:
    return Mock(
        url=url,
        merge_requests_events=mr,
        push_events=push,
        note_events=note,
    )


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


@pytest.mark.parametrize("dry_run", [True, False])
def test_jenkins_webhooks_cleaner_removes_only_identical_hooks(
    dry_run: bool, mocker: MockerFixture
) -> None:
    mocker.patch("reconcile.jenkins_webhooks_cleaner.queries.get_gitlab_instance")
    mocker.patch("reconcile.jenkins_webhooks_cleaner.get_app_interface_vault_settings")
    mocker.patch("reconcile.jenkins_webhooks_cleaner.create_secret_reader")
    mocker.patch(
        "reconcile.jenkins_webhooks_cleaner.queries.get_jenkins_instances_previous_urls",
        return_value=["https://old-jenkins.example.com"],
    )
    mocker.patch(
        "reconcile.jenkins_webhooks_cleaner.queries.get_repos",
        return_value=[PROJECT_URL],
    )
    gl = mocker.patch("reconcile.jenkins_webhooks_cleaner.GitLabApi").return_value
    gl.server = "https://gitlab.example.com"
    first = make_hook(JOB_URL, mr=True)
    duplicate = make_hook(JOB_URL + "/", mr=True)
    different_trigger = make_hook(JOB_URL, push=True)
    old_url = make_hook("https://old-jenkins.example.com/job", mr=True)
    gl.get_project_hooks.return_value = [first, duplicate, different_trigger, old_url]

    jenkins_webhooks_cleaner.run(dry_run=dry_run)

    first.delete.assert_not_called()
    different_trigger.delete.assert_not_called()
    assert duplicate.delete.call_count == (0 if dry_run else 1)
    assert old_url.delete.call_count == (0 if dry_run else 1)
