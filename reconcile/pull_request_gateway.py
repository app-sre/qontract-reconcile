import reconcile.queries as queries

from utils.sqs_gateway import SQSGateway
from utils.gitlab_api import GitLabApi


class PullRequestGatewayError(Exception):
    pass


def init(gitlab_project_id=None):
    settings = queries.get_app_interface_settings()
    pr_gateway_type = settings.get('pullRequestGateway', 'gitlab')

    if pr_gateway_type == 'gitlab':
        instance = queries.get_gitlab_instance()
        if gitlab_project_id is None:
            raise PullRequestGatewayError('missing gitlab project id')
        return GitLabApi(instance, project_id=gitlab_project_id)
    elif pr_gateway_type == 'sqs':
        return SQSGateway()
