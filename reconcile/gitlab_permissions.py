from typing import Any

from reconcile import queries
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi

QONTRACT_INTEGRATION = "gitlab-permissions"
APP_SRE_GROUP_NAME = "app-sre"


@defer
def run(dry_run, defer=None):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    if defer:
        defer(gl.cleanup)
    repos = queries.get_repos(server=gl.server, exclude_manage_permissions=True)
    group_id, shared_projects = gl.get_group_id_and_shared_projects(APP_SRE_GROUP_NAME)
    shared_project_repos = {project["web_url"] for project in shared_projects}
    repos_to_share = set(repos) - shared_project_repos
    for repo in repos_to_share:
        gl.share_project_with_group(repo_url=repo, group_id=group_id, dry_run=dry_run)


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
        "repos": queries.get_repos(server=instance["url"]),
    }
