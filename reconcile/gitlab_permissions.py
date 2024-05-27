import itertools
import logging
from typing import Any

from reconcile import queries
from reconcile.utils import batches
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi

QONTRACT_INTEGRATION = "gitlab-permissions"
PAGE_SIZE = 100
APP_SRE_GROUP_NAME = "app-sre"


def get_members_to_add(repo, gl, app_sre):
    maintainers = get_all_app_sre_maintainers(repo, gl, app_sre)
    if maintainers is None:
        return []
    if gl.user.username not in maintainers:
        logging.error(
            "'{}' is not shared with {} as 'Maintainer'".format(repo, gl.user.username)
        )
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
    logging.debug(len(repos))
    group_id, shared_projects = gl.get_group_id_and_shared_projects(APP_SRE_GROUP_NAME)
    shared_project_repos = [project["web_url"] for project in shared_projects]
    repos_to_share = [repo_url for repo_url in set(repos) - set(shared_project_repos)]
    for repo in repos_to_share:
        logging.info(["add_group_as_maintainer", repo, "app-sre"])
        if not dry_run:
            gl.share_project_with_group(repo_url=repo, group_id=group_id)


def get_id_to_repo_mapping(repo, gl):
    return {gl.get_project(repo_url=repo).get_id(): repo}


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
        "repos": queries.get_repos(server=instance["url"]),
    }
