import logging
import sys
from collections.abc import Callable
from operator import eq
from typing import Any

from qontract_utils.differ import diff_mappings

from reconcile import queries
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi

QONTRACT_INTEGRATION = "gitlab-projects"


def reconcile_project_shared_groups(
    gl: GitLabApi,
    project_url: str,
    shared_with_groups: list[dict[str, str]],
    dry_run: bool,
) -> None:
    desired = {
        sg["group"]: gl.get_access_level(sg["accessLevel"])
        for sg in shared_with_groups
    }
    project = gl.get_project(project_url)
    if project is None:
        for group_name, access_level in desired.items():
            logging.info([
                "share_project_with_group",
                project_url,
                group_name,
                gl.get_access_level_string(access_level),
            ])
        return

    current = gl.get_project_shared_groups(project)
    diff_data = diff_mappings(
        current=current,
        desired=desired,
        equal=eq,
    )
    for group_name, access_level in diff_data.add.items():
        access = gl.get_access_level_string(access_level)
        logging.info(["share_project_with_group", project_url, group_name, access])
        if not dry_run:
            gl.share_project_with_group(project, group_name, access)
    for group_name in diff_data.delete:
        logging.info(["unshare_project_from_group", project_url, group_name])
        if not dry_run:
            gl.unshare_project_from_group(project, group_name)
    for group_name, diff_pair in diff_data.change.items():
        access = gl.get_access_level_string(diff_pair.desired)
        logging.info(["change_shared_group_access", project_url, group_name, access])
        if not dry_run:
            gl.unshare_project_from_group(project, group_name)
            gl.share_project_with_group(project, group_name, access)


@defer
def run(dry_run: bool, defer: Callable | None = None) -> None:
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    code_components = queries.get_code_components()
    app_int_repos = [c["url"] for c in code_components]
    saas_bundle_repos = [c["url"] for c in code_components if c["resource"] == "bundle"]
    gl = GitLabApi(instance, settings=settings)
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

        if "sharedWithGroups" in pr:
            for p in requested_projects:
                project_url = gl.get_project_url(group, p)
                reconcile_project_shared_groups(
                    gl=gl,
                    project_url=project_url,
                    shared_with_groups=pr["sharedWithGroups"],
                    dry_run=dry_run,
                )

    sys.exit(error)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
    }
