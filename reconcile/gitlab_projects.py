import logging
import sys
from typing import Any

from reconcile import queries
from reconcile.utils.gitlab_api import GitLabApi

QONTRACT_INTEGRATION = "gitlab-projects"


def run(dry_run):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    code_components = queries.get_code_components()
    app_int_repos = [c["url"] for c in code_components]
    saas_bundle_repos = [c["url"] for c in code_components if c["resource"] == "bundle"]
    gl = GitLabApi(instance, settings=settings)

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


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
    }
