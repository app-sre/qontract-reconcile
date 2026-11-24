from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from reconcile import queries
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.jenkins import get_jenkins_instances
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import create_secret_reader

if TYPE_CHECKING:
    from collections.abc import Callable

    from gitlab.v4.objects import ProjectHook, ProjectHookManager

QONTRACT_INTEGRATION = "jenkins-webhooks-cleaner"

type HookKey = tuple[str, tuple[tuple[str, bool], ...], str | None]

MANAGED_TRIGGERS = {
    frozenset({"push_events"}),
    frozenset({"merge_requests_events", "note_events"}),
    frozenset({"note_events"}),
}
MANAGED_EVENT_FIELDS = {"push_events", "merge_requests_events", "note_events"}
DETAIL_ONLY_FIELDS = {"custom_headers", "url_variables"}
UNMANAGED_SETTINGS = (
    "push_events_branch_filter",
    "custom_webhook_template",
    "duo_flow_callback_enabled",
    "name",
    "description",
    "disabled_until",
)


def _job_prefix(url: str) -> str:
    return f"{url.rstrip('/')}/project/"


def _managed_hook_key(
    hook: ProjectHook, prefixes: tuple[str, ...], *, complete: bool = False
) -> HookKey | None:
    """Identify only hooks that match the integration's Jenkins job contract."""
    url = hook.url.rstrip("/")
    if not any(url.startswith(prefix) for prefix in prefixes):
        return None

    attrs = getattr(hook, "attributes", None)
    if not isinstance(attrs, Mapping) or not MANAGED_EVENT_FIELDS.issubset(attrs):
        return None
    if complete and not DETAIL_ONLY_FIELDS.issubset(attrs):
        return None
    if complete and (
        attrs.get("token_present") is not False
        or attrs.get("signing_token_present") is not False
    ):
        return None
    if attrs.get("enable_ssl_verification") is not True:
        return None
    if any(attrs.get(field) for field in UNMANAGED_SETTINGS):
        return None
    if complete and any(attrs.get(field) for field in DETAIL_ONLY_FIELDS):
        return None

    event_settings = tuple(
        sorted(
            (field, bool(value))
            for field, value in attrs.items()
            if field.endswith("_events")
        )
    )
    enabled_events = frozenset(field for field, enabled in event_settings if enabled)
    if enabled_events not in MANAGED_TRIGGERS:
        return None

    return url, event_settings, attrs.get("branch_filter_strategy")


def _get_details(hook: ProjectHook, cache: dict[int, ProjectHook]) -> ProjectHook:
    # The list response omits custom headers and URL variables. Fetch a full
    # hook only when it becomes a deletion candidate.
    if hook.id not in cache:
        cache[hook.id] = cast("ProjectHookManager", hook.manager).get(hook.id)
    return cache[hook.id]


@defer
def run(dry_run: bool, defer: Callable | None = None) -> None:
    instance = queries.get_gitlab_instance()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    gl = GitLabApi(instance, secret_reader=secret_reader)
    if defer:
        defer(gl.cleanup)
    current_prefixes = tuple(
        _job_prefix(instance.server_url) for instance in get_jenkins_instances()
    )
    previous_prefixes = tuple(
        _job_prefix(url) for url in queries.get_jenkins_instances_previous_urls()
    )
    repos = queries.get_repos(server=gl.server)

    for repo in repos:
        seen_hooks: dict[HookKey, list[ProjectHook]] = {}
        details: dict[int, ProjectHook] = {}
        hook_id: int | None = None
        deleting_hook_id: int | None = None

        try:
            hooks = gl.get_project_hooks(repo)
            for hook in hooks:
                hook_id = hook.id
                current_key = _managed_hook_key(hook, current_prefixes)
                previous_key = _managed_hook_key(hook, previous_prefixes)
                if previous_key is not None:
                    previous_detail = _get_details(hook, details)
                    if (
                        _managed_hook_key(
                            previous_detail, previous_prefixes, complete=True
                        )
                        is not None
                    ):
                        logging.info(["delete_hook", repo, hook.id, hook.url])
                        if not dry_run:
                            deleting_hook_id = hook.id
                            hook.delete()
                            deleting_hook_id = None
                    continue
                if current_key is None:
                    continue

                seen = seen_hooks.setdefault(current_key, [])
                if not seen:
                    seen.append(hook)
                    continue

                candidate_detail = _get_details(hook, details)
                candidate_key = _managed_hook_key(
                    candidate_detail, current_prefixes, complete=True
                )
                for existing in seen:
                    existing_detail = _get_details(existing, details)
                    existing_key = _managed_hook_key(
                        existing_detail, current_prefixes, complete=True
                    )
                    if candidate_key is None or candidate_key != existing_key:
                        continue
                    if existing_detail.attributes.get("alert_status") == "executable":
                        logging.info(["delete_hook", repo, hook.id, hook.url])
                        if not dry_run:
                            deleting_hook_id = hook.id
                            hook.delete()
                            deleting_hook_id = None
                        break
                    if candidate_detail.attributes.get("alert_status") == "executable":
                        logging.info(["delete_hook", repo, existing.id, existing.url])
                        if not dry_run:
                            deleting_hook_id = existing.id
                            existing.delete()
                            deleting_hook_id = None
                        seen.remove(existing)
                        seen.append(hook)
                        break
                else:
                    seen.append(hook)
        except Exception:
            if deleting_hook_id is not None:
                logging.exception(
                    "Failed deleting Jenkins webhook %s in %s; continuing with next repository",
                    deleting_hook_id,
                    repo,
                )
            else:
                logging.exception(
                    "Failed inspecting Jenkins webhooks for %s at hook %s; "
                    "continuing with next repository",
                    repo,
                    hook_id,
                )


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "previous_urls": queries.get_jenkins_instances_previous_urls(),
    }
