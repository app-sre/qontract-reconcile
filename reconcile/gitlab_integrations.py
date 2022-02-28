import logging

from sretoolbox.utils import retry

from reconcile.utils.secret_reader import SecretReader
from reconcile import queries

from reconcile.utils.gitlab_api import GitLabApi

QONTRACT_INTEGRATION = "gitlab-integrations"


@retry()
def get_repo_services(gl, repo_url):
    project = gl.get_project(repo_url=repo_url)
    return project.services


def run(dry_run):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    secret_reader = SecretReader(settings=settings)

    # Jira
    repos = queries.get_repos_gitlab_jira(server=gl.server)
    for repo in repos:
        skip = False
        repo_url = repo["url"]
        services = get_repo_services(gl, repo_url)
        current_jira = services.get("jira")

        desired_jira = repo["jira"]
        desired_jira_url = desired_jira["serverUrl"]
        desired_jira_crdentials = secret_reader.read_all(desired_jira["token"])

        if current_jira.active:
            properties = current_jira.properties
            desired_jira_username = desired_jira_crdentials["username"]
            if (
                properties["url"] == desired_jira_url
                and properties["username"] == desired_jira_username
            ):
                skip = True

        if skip:
            continue

        logging.info(["update_jira", repo_url, desired_jira_url])
        if not dry_run:
            new_data = {
                "active": True,
                "url": desired_jira_url,
                "username": desired_jira_crdentials["username"],
                "password": desired_jira_crdentials["password"],
                "commit_events": True,
                "merge_requests_events": True,
                "comment_on_event_enabled": False,
            }
            services.update("jira", new_data=new_data)
