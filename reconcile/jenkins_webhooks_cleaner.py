import logging
from typing import Any

from reconcile import queries
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi

QONTRACT_INTEGRATION = "jenkins-webhooks-cleaner"


@defer
def run(dry_run, defer=None):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    if defer:
        defer(gl.cleanup)
    previous_urls = queries.get_jenkins_instances_previous_urls()
    repos = queries.get_repos(server=gl.server)

    for repo in repos:
        found_hook_urls = set()
        try:
            hooks = gl.get_project_hooks(repo)
            for hook in hooks:
                hook_url = hook.url
                if hook_url in found_hook_urls:
                    # duplicate! remove
                    logging.info(["delete_hook", repo, hook_url])
                    if not dry_run:
                        hook.delete()
                    continue
                found_hook_urls.add(hook_url)
                for previous_url in previous_urls:
                    if hook_url.startswith(previous_url):
                        logging.info(["delete_hook", repo, hook_url])
                        if not dry_run:
                            hook.delete()
        except Exception:
            logging.warning("no access to project: " + repo)


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    return {
        "previous_urls": queries.get_jenkins_instances_previous_urls(),
    }
