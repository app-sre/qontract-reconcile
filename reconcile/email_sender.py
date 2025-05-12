import logging
import sys
from collections.abc import Callable

from reconcile import typed_queries
from reconcile.gql_definitions.email_sender.apps import query as apps_query
from reconcile.gql_definitions.email_sender.emails import (
    AppInterfaceEmailAudienceV1,
    AppInterfaceEmailV1,
)
from reconcile.gql_definitions.email_sender.emails import query as emails_query
from reconcile.gql_definitions.email_sender.users import query as users_query
from reconcile.gql_definitions.fragments.email_service import EmailServiceOwners
from reconcile.gql_definitions.fragments.email_user import EmailUser
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


def collect_to(
    to: AppInterfaceEmailAudienceV1,
    all_users: list[EmailUser],
    all_services: list[EmailServiceOwners],
) -> set[str]:
    """Collect audience to send email to from to object

    Arguments:
        to -- AppInterfaceEmailAudience_v1 object
        all_users -- List of all app-interface users
        all_services -- List of all app-interface apps/services with owners

    Raises:
        AttributeError: Unknown alias

    Returns:
        set -- Audience to send email to
    """
    audience: set[str] = set()

    for alias in to.aliases or []:
        match alias:
            case "all-users":
                to.users = all_users
            case "all-service-owners":
                to.services = all_services
            case _:
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

    # SmtpClient supports sending to org_username and email addresses
    audience.update(user.org_username for user in to.users or [])

    if to.clusters or to.namespaces:
        raise NotImplementedError("clusters and namespaces are not implemented yet")
    return audience


def get_emails(query_func: Callable) -> list[AppInterfaceEmailV1]:
    return emails_query(query_func).emails or []


@defer
def run(dry_run: bool, defer: Callable | None = None) -> None:
    gql_api = gql.get_api()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    state = init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader)
    if defer:
        defer(state.cleanup)

    emails = get_emails(gql_api.query)
    if not emails:
        logging.info("no emails to send")
        sys.exit(0)

    all_users = users_query(gql_api.query).users or []
    all_services = apps_query(gql_api.query).apps or []
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
            names = collect_to(
                email.q_to, all_users=all_users, all_services=all_services
            )
            smtp_client.send_mail(names, email.subject, email.body)
            state.add(email.name)
