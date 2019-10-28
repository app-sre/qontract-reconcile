import reconcile.queries as queries

from utils.aws_api import AWSApi
from utils.gitlab_api import GitLabApi


def init(gitlab_project_id=None):
    settings = queries.get_app_interface_settings()
    pr_gateway_type = settings.get('pullRequestGateway', 'gitlab')

    if pr_gateway_type == 'gitlab':
        instance = queries.get_gitlab_instance()
        return GitLabApi(instance, project_id=gitlab_project_id)
    elif pr_gateway_type == 'sqs':
        accounts = queries.get_aws_accounts()
        return AWSApi(thread_pool_size, accounts)
