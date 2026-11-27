from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qontract_utils.differ import diff_iterables

from reconcile import queries
from reconcile.jenkins_job_builder import init_jjb
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import SecretReader

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


QONTRACT_INTEGRATION = "jenkins-webhooks"


def get_gitlab_api(secret_reader: SecretReader) -> GitLabApi:
    instance = queries.get_gitlab_instance()
    return GitLabApi(instance, secret_reader=secret_reader)


def get_hooks_to_add(
    desired_state: Mapping[str, list[dict[str, Any]]], gl: GitLabApi
) -> dict[str, list[dict[str, Any]]]:
    diff: dict[str, list[dict[str, Any]]] = {}
    for project_url, desired_hooks in desired_state.items():
        try:
            current_hooks = gl.get_project_hooks(project_url)
        except Exception:
            logging.exception(
                "Unable to list hooks for %s; skipping creation", project_url
            )
            diff[project_url] = []
            continue

        current = [
            {
                "job_url": hook.url.strip("/"),
                "trigger": [
                    event
                    for event, enabled in (
                        ("mr", hook.merge_requests_events),
                        ("push", hook.push_events),
                        ("note", hook.note_events),
                    )
                    if enabled
                ],
            }
            for hook in current_hooks
        ]
        hooks_diff = diff_iterables(
            current,
            desired_hooks,
            key=lambda hook: (hook["job_url"].strip("/"), frozenset(hook["trigger"])),
        )
        diff[project_url] = list(hooks_diff.add.values())

    return diff


@defer
def run(dry_run: bool, defer: Callable | None = None) -> None:
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    jjb = init_jjb(secret_reader)
    gl = get_gitlab_api(secret_reader)
    if defer:
        defer(gl.cleanup)

    desired_state = jjb.get_job_webhooks_data()
    diff = get_hooks_to_add(desired_state, gl)

    for project_url, hooks in diff.items():
        for h in hooks:
            logging.info(["create_hook", project_url, h["trigger"], h["job_url"]])

            if not dry_run:
                gl.create_project_hook(project_url, h)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "jenkins_configs": queries.get_jenkins_configs(),
    }
