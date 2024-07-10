import itertools
import logging
from dataclasses import dataclass
from typing import Any

from gitlab.const import MAINTAINER_ACCESS
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils import batches
from reconcile.utils.defer import defer
from reconcile.utils.differ import diff_mappings
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.unleash import get_feature_toggle_state

QONTRACT_INTEGRATION = "gitlab-permissions"
APP_SRE_GROUP_NAME = "app-sre"
PAGE_SIZE = 100


@dataclass
class GroupSpec:
    group_name: str
    group_access_level: int


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
    non_app_sre_project_repos = {
        repo
        for repo in repos
        if not gl.is_group_project_owner(group_name=APP_SRE_GROUP_NAME, repo_url=repo)
    }
    desired_state = {
        project_repo_url: GroupSpec(APP_SRE_GROUP_NAME, MAINTAINER_ACCESS)
        for project_repo_url in non_app_sre_project_repos
    }
    group_id, shared_projects = gl.get_group_id_and_shared_projects(APP_SRE_GROUP_NAME)
    current_state = {
        project_repo_url: GroupSpec(
            shared_projects[project_repo_url]["group_name"],
            shared_projects[project_repo_url]["group_access_level"],
        )
        for project_repo_url in shared_projects
    }

    # get the diff data
    diff_data = diff_mappings(
        current=current_state,
        desired=desired_state,
        equal=lambda current, desired: current.group_access_level
        == desired.group_access_level,
    )

    for repo in diff_data.add.keys():
        gl.share_project_with_group(repo_url=repo, group_id=group_id, dry_run=dry_run)

    for repo in diff_data.change.keys():
        gl.share_project_with_group(
            repo_url=repo, group_id=group_id, dry_run=dry_run, reshare=True
        )


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
        "repos": queries.get_repos(server=instance["url"]),
    }
