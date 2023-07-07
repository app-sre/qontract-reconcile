import logging
import sys

from reconcile.gql_definitions.jira_permissions_validator.jira_boards_for_permissions_validator import (
    query as query_jira_boards,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.jira_settings import get_jira_settings
from reconcile.utils import gql
from reconcile.utils.jira_client import JiraClient
from reconcile.utils.secret_reader import create_secret_reader

QONTRACT_INTEGRATION = "jira-permissions-validator"


def run(dry_run: bool) -> None:
    gql_api = gql.get_api()
    settings = get_jira_settings(gql_api=gql_api)
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    jira_boards = query_jira_boards(query_func=gql_api.query).jira_boards or []
    error = False
    for jira_board in jira_boards:
        token = secret_reader.read_secret(jira_board.server.token)
        jira = JiraClient.create(
            project_name=jira_board.name,
            token=token,
            server_url=jira_board.server.server_url,
            jira_watcher_settings=settings.jira_watcher,
        )
        if not jira.can_create_issues():
            error = True
            logging.error(f"can not create issues in project {jira.project}")

    if error:
        sys.exit(ExitCodes.ERROR)
