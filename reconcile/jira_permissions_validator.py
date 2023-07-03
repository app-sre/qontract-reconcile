import logging
import sys

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.jira_client import JiraClient

QONTRACT_INTEGRATION = "jira-permissions-validator"


def run(dry_run: bool) -> None:
    settings = queries.get_app_interface_settings()
    error = False
    for jira_board in queries.get_jira_boards(with_slack=False):
        jira = JiraClient(jira_board, settings=settings)
        if not jira.can_create_issues():
            error = True
            logging.error(f"can not create issues in project {jira.project}")

    if error:
        sys.exit(ExitCodes.ERROR)
