import itertools
import logging
from typing import Any

from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils.gitlab_api import GitLabApi

QONTRACT_INTEGRATION = "gitlab-permissions"


def get_members_to_add(repo, gl, app_sre):
    maintainers = gl.get_project_maintainers(repo)
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


def run(dry_run, thread_pool_size=10):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    repos = queries.get_repos(server=gl.server)
    app_sre = gl.get_app_sre_group_users()
    results = threaded.run(
        get_members_to_add, repos, thread_pool_size, gl=gl, app_sre=app_sre
    )

    members_to_add = list(itertools.chain.from_iterable(results))
    for m in members_to_add:
        logging.info(["add_maintainer", m["repo"], m["user"].username])
        if not dry_run:
            gl.add_project_member(m["repo"], m["user"])


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
        "repos": queries.get_repos(server=instance["url"]),
    }
