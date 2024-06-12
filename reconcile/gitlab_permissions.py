import itertools
import logging
from typing import Any

from gitlab.const import MAINTAINER_ACCESS
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils import batches
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.unleash import get_feature_toggle_state

QONTRACT_INTEGRATION = "gitlab-permissions"
APP_SRE_GROUP_NAME = "app-sre"
PAGE_SIZE = 100


def get_members_to_add(repo, gl, app_sre):
    maintainers = get_all_app_sre_maintainers(repo, gl, app_sre)
    if maintainers is None:
        return []
    if gl.user.username not in maintainers:
        logging.error(f"'{repo}' is not shared with {gl.user.username} as 'Maintainer'")
        return []
    members_to_add = [
        {"user": u, "repo": repo} for u in app_sre if u.username not in maintainers
    ]
    return members_to_add


def get_all_app_sre_maintainers(repo, gl, app_sre):
    app_sre_user_ids = [user.id for user in app_sre]
    chunks = batches.batched(app_sre_user_ids, PAGE_SIZE)
    app_sre_maintainers = (
        gl.get_project_maintainers(repo, query=create_user_ids_query(chunk))
        for chunk in chunks
    )
    return list(itertools.chain.from_iterable(app_sre_maintainers))


def create_user_ids_query(ids):
    return {"user_ids": ",".join(str(id) for id in ids)}


@defer
def run(dry_run, thread_pool_size=10, defer=None):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    if defer:
        defer(gl.cleanup)
    repos = queries.get_repos(server=gl.server, exclude_manage_permissions=True)
    share_with_group_enabled = get_feature_toggle_state(
        "gitlab-permissions-share-with-group",
        default=False,
    )
    if share_with_group_enabled:
        share_project_with_group(gl, repos, dry_run)
    else:
        share_project_with_group_members(gl, repos, thread_pool_size, dry_run)


def share_project_with_group_members(
    gl: GitLabApi, repos: list[str], thread_pool_size: int, dry_run: bool
) -> None:
    app_sre = gl.get_app_sre_group_users()
    results = threaded.run(
        get_members_to_add, repos, thread_pool_size, gl=gl, app_sre=app_sre
    )
    members_to_add = list(itertools.chain.from_iterable(results))
    for m in members_to_add:
        logging.info(["add_maintainer", m["repo"], m["user"].username])
        if not dry_run:
            gl.add_project_member(m["repo"], m["user"])


def share_project_with_group(gl: GitLabApi, repos: list[str], dry_run: bool) -> None:
    # get repos not owned by app-sre
    non_app_sre_project_repos = {repo for repo in repos if "/app-sre/" not in repo}
    group_id, shared_projects = gl.get_group_id_and_shared_projects(APP_SRE_GROUP_NAME)
    shared_project_repos = shared_projects.keys()
    repos_to_share = non_app_sre_project_repos - shared_project_repos
    repos_to_reshare = {
        repo
        for repo in non_app_sre_project_repos
        if (group_data := shared_projects.get(repo))
        and group_data["group_access_level"] < MAINTAINER_ACCESS
    }
    for repo in repos_to_share:
        gl.share_project_with_group(repo_url=repo, group_id=group_id, dry_run=dry_run)
    for repo in repos_to_reshare:
        gl.share_project_with_group(
            repo_url=repo, group_id=group_id, dry_run=dry_run, reshare=True
        )


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
        "repos": queries.get_repos(server=instance["url"]),
    }
