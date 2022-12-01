from collections.abc import Mapping
from typing import Any

from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.sqs_gateway import SQSGateway


class MRClientGatewayError(Exception):
    """
    Used when an error happens in the MR Client Gateway initialization.
    """


MR_GW_QUERY = """
{
  settings: app_interface_settings_v1 {
    vault
    mergeRequestGateway
  }
}
"""


def get_mr_gateway_settings() -> Mapping[str, Any]:
    """Returns SecretReader settings"""
    gqlapi = gql.get_api()
    settings = gqlapi.query(MR_GW_QUERY)["settings"]
    if settings:
        # assuming a single settings file for now
        return settings[0]
    else:
        raise ValueError("no app-interface-settings found")


def init(gitlab_project_id=None, sqs_or_gitlab=None):
    """
    Creates the Merge Request client to of a given type.

    :param gitlab_project_id: used when the client type is 'gitlab'
    :param sqs_or_gitlab: 'gitlab' or 'sqs'
    :return: an instance of the selected MR client.
    """
    settings = get_mr_gateway_settings()
    if sqs_or_gitlab is None:
        client_type = settings.get("mergeRequestGateway", "gitlab")
    else:
        client_type = sqs_or_gitlab

    if client_type == "gitlab":
        if gitlab_project_id is None:
            raise MRClientGatewayError('Missing "gitlab_project_id".')

        instance = queries.get_gitlab_instance()
        return GitLabApi(
            instance,
            project_id=gitlab_project_id,
            secret_reader=SecretReader(settings),
        )

    elif client_type == "sqs":
        accounts = queries.get_queue_aws_accounts()

        return SQSGateway(accounts, secret_reader=SecretReader(settings))

    else:
        raise MRClientGatewayError(f"Invalid client type: {client_type}")
