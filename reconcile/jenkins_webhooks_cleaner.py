from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from reconcile import queries
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import create_secret_reader

if TYPE_CHECKING:
    from collections.abc import Callable

QONTRACT_INTEGRATION = "jenkins-webhooks-cleaner"


@defer
def run(dry_run: bool, defer: Callable | None = None) -> None:
    instance = queries.get_gitlab_instance()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    gl = GitLabApi(instance, secret_reader=secret_reader)
    if defer:
        defer(gl.cleanup)
    previous_urls = queries.get_jenkins_instances_previous_urls()
    repos = queries.get_repos(server=gl.server)

    for repo in repos:
        found_hooks: set[tuple[str, bool, bool, bool]] = set()
        try:
            hooks = gl.get_project_hooks(repo)
        except Exception:
            logging.exception("Unable to list hooks for %s; skipping cleanup", repo)
            continue

        for hook in hooks:
            hook_url = hook.url
            if any(hook_url.startswith(url) for url in previous_urls):
                logging.info(["delete_hook", repo, hook_url])
                if not dry_run:
                    hook.delete()
                continue

            hook_key = (
                hook_url.strip("/"),
                bool(hook.merge_requests_events),
                bool(hook.push_events),
                bool(hook.note_events),
            )
            if hook_key in found_hooks:
                logging.info(["delete_hook", repo, hook_url])
                if not dry_run:
                    hook.delete()
                continue
            found_hooks.add(hook_key)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "previous_urls": queries.get_jenkins_instances_previous_urls(),
    }
