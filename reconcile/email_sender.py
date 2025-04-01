import logging
import sys
from collections.abc import Callable

from reconcile import typed_queries
from reconcile.gql_definitions.email_sender.apps import query as apps_query
from reconcile.gql_definitions.email_sender.emails import AppInterfaceEmailAudienceV1
from reconcile.gql_definitions.email_sender.emails import query as emails_query
from reconcile.gql_definitions.email_sender.users import query as users_query
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.smtp_client import (
    DEFAULT_SMTP_TIMEOUT,
    SmtpClient,
    get_smtp_server_connection,
)
from reconcile.utils.state import init_state

QONTRACT_INTEGRATION = "email-sender"


def collect_to(query_func: Callable, to: AppInterfaceEmailAudienceV1) -> set[str]:
    """Collect audience to send email to from to object

    Arguments:
        to -- AppInterfaceEmailAudience_v1 object

    Raises:
        AttributeError: Unknown alias

    Returns:
        set -- Audience to send email to
    """
    audience: set[str] = set()

    for alias in to.aliases or []:
        if alias == "all-users":
            to.users = users_query(query_func).users or []
        elif alias == "all-service-owners":
            to.services = apps_query(query_func).apps or []
        else:
            raise AttributeError(f"unknown alias: {alias}")

    for service in to.services or []:
        audience.update(
            service_owner.email for service_owner in service.service_owners or []
        )

    for account in to.aws_accounts or []:
        audience.update(
            account_owner.email for account_owner in account.account_owners or []
        )

    for role in to.roles or []:
        audience.update(user.org_username for user in role.users or [])

    audience.update(user.org_username for user in to.users or [])
    # TODO: implement clusters and namespaces
    return audience


@defer
def run(dry_run: bool, defer: Callable | None = None) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    state = init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader)
    if defer:
        defer(state.cleanup)
    gql_api = gql.get_api()
    emails = emails_query(gql_api.query).emails or []
    if not emails:
        logging.info("no emails to send")
        sys.exit(0)
    smtp_settings = typed_queries.smtp.settings()
    smtp_client = SmtpClient(
        server=get_smtp_server_connection(
            secret_reader=secret_reader,
            secret=smtp_settings.credentials,
        ),
        mail_address=smtp_settings.mail_address,
        timeout=smtp_settings.timeout or DEFAULT_SMTP_TIMEOUT,
    )
    # validate no 2 emails have the same name
    email_names = {e.name for e in emails}
    if len(emails) != len(email_names):
        logging.error("email names must be unique.")
        sys.exit(1)

    emails_to_send = [e for e in emails if not state.exists(e.name)]
    for email in emails_to_send:
        logging.info(["send_email", email.name, email.subject])

        if not dry_run:
            names = collect_to(gql_api.query, email.q_to)
            smtp_client.send_mail(names, email.subject, email.body)
            state.add(email.name)
