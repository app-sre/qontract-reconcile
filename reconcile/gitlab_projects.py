from __future__ import annotations

import logging
import sys
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

QONTRACT_INTEGRATION = "gitlab-projects"


@defer
def run(dry_run: bool, defer: Callable | None = None) -> None:
    instance = queries.get_gitlab_instance()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    code_components = queries.get_code_components()
    app_int_repos = [c["url"] for c in code_components]
    saas_bundle_repos = [c["url"] for c in code_components if c["resource"] == "bundle"]
    gl = GitLabApi(instance, secret_reader=secret_reader)
    if defer:
        defer(gl.cleanup)

    project_requests = instance["projectRequests"] or []
    error = False
    for pr in project_requests:
        group = pr["group"]
        group_id, existing_projects = gl.get_group_id_and_projects(group)
        requested_projects = pr["projects"]
        projects_to_create = [
            p for p in requested_projects if p not in existing_projects
        ]
        for p in projects_to_create:
            project_url = gl.get_project_url(group, p)
            if project_url not in app_int_repos:
                logging.error(f"{project_url} missing from all codeComponents")
                error = True
                continue
            logging.info(["create_project", group, p])
            if not dry_run:
                gl.create_project(group_id, p)
            if project_url in saas_bundle_repos:
                logging.info(["initiate_saas_bundle_repo", group, p])
                if not dry_run:
                    gl.initiate_saas_bundle_repo(project_url)

    sys.exit(error)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
    }
