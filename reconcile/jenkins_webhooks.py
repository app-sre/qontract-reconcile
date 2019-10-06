import copy
import logging

import utils.gql as gql

from utils.gitlab_api import GitLabApi
from reconcile.jenkins_job_builder import init_jjb
from reconcile.queries import GITLAB_INSTANCES_QUERY


def get_gitlab_api():
    gqlapi = gql.get_api()
    # assuming a single GitLab instance for now
    instance = gqlapi.query(GITLAB_INSTANCES_QUERY)['instances'][0]
    return GitLabApi(instance)


def get_hooks_to_add(desired_state, gl):
    diff = copy.deepcopy(desired_state)
    for project_url, desired_hooks in diff.items():
        try:
            current_hooks = gl.get_project_hooks(project_url)
            for h in current_hooks:
                job_url = h.url
                trigger = 'mr' if h.merge_requests_events else 'push'
                item = {
                    'job_url': job_url.strip('/'),
                    'trigger': trigger,
                }
                if item in desired_hooks:
                    desired_hooks.remove(item)
        except Exception:
            logging.warning('no access to project: ' + project_url)
            diff[project_url] = []

    return diff


def run(dry_run=False):
    jjb, _ = init_jjb()
    gl = get_gitlab_api()

    desired_state = jjb.get_job_webhooks_data()
    diff = get_hooks_to_add(desired_state, gl)

    for project_url, hooks in diff.items():
        for h in hooks:
            logging.info(['create_hook', project_url,
                          h['trigger'], h['job_url']])

            if not dry_run:
                gl.create_project_hook(project_url, h)
