import logging

import reconcile.queries as queries

from utils.sqs_gateway import SQSGateway
from utils.gitlab_api import GitLabApi


class PullRequestGatewayError(Exception):
    pass


def get_pr_gateway_type():
    settings = queries.get_app_interface_settings()
    return settings.get('pullRequestGateway') or 'gitlab'


def init(gitlab_project_id=None, override_pr_gateway_type=None):
    pr_gateway_type = override_pr_gateway_type or get_pr_gateway_type()

    if pr_gateway_type == 'gitlab':
        instance = queries.get_gitlab_instance()
        if gitlab_project_id is None:
            raise PullRequestGatewayError('missing gitlab project id')
        return GitLabApi(instance, project_id=gitlab_project_id)
    elif pr_gateway_type == 'sqs':
        accounts = queries.get_aws_accounts()
        return SQSGateway(accounts)
    else:
        raise PullRequestGatewayError(
            'invalid pull request gateway: {}'.format(pr_gateway_type))


def submit_to_gitlab(gitlab_project_id, dry_run):
    client = init()
    gl = init(gitlab_project_id=gitlab_project_id,
              override_pr_gateway_type='gitlab')

    # adding this condition as safety. it is not really needed because
    # client = init() will fail if the pull request gateway
    # is 'gitlab' but gitlab_project_id is None
    if type(client) == type(gl):
        logging.info('pull request gateway is gitlab, nothing to do')
        return

    # using while instead of iterating over the queue
    # since additional messages may be coming in
    while True:
        messages = client.receive_messages()
        if not messages:
            break
        for m in messages:
            receipt_handle, body = m[0], m[1]
            pr_type = body['pr_type']
            if pr_type == 'create_delete_aws_access_key_mr':
                account, path, key = \
                    body['account'], body['path'], body['key']
                logging.info([pr_type, account, key])
                if not dry_run:
                    gl.create_delete_aws_access_key_mr(account, path, key)
            elif pr_type == 'create_delete_user_mr':
                username, paths = body['username'], body['paths']
                logging.info([pr_type, username])
                if not dry_run:
                    gl.create_delete_user_mr(username, paths)
            else:
                raise PullRequestGatewayError(
                    'invalid pull request type: {}'.format(pr_type))
            if not dry_run:
                client.delete_message(receipt_handle)
