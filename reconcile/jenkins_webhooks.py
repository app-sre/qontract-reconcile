from utils.config import get_config
from utils.gitlab_api import GitLabApi
from reconcile.jenkins_job_builder import init_jjb


def get_gitlab_api():
    config = get_config()

    gitlab_config = config['gitlab']
    server = gitlab_config['server']
    token = gitlab_config['token']

    return GitLabApi(server, token, ssl_verify=False)


def run(dry_run=False):
    jjb = init_jjb()
    data = jjb.get_job_webhooks_data()

    gl = get_gitlab_api()

    for d in data:
        print(d['job_name'])
        hooks = gl.get_project_hooks(d['repo_url'])
        print(hooks)


# trigger-merge-request - True or False
# trigger-open-merge-request-push - source or never
# add-note-merge-request - True or False
# add-vote-merge-request - True or False
# add-ci-message - True or False
