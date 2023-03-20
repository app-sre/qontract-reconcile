import logging
import sys

from reconcile import (
    queries,
    typed_queries,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.defer import defer
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.smtp_client import (
    DEFAULT_SMTP_TIMEOUT,
    SmtpClient,
    get_smtp_server_connection,
)
from reconcile.utils.state import init_state

QONTRACT_INTEGRATION = "email-sender"


def collect_to(to):
    """Collect audience to send email to from to object

    Arguments:
        to {dict} -- AppInterfaceEmailAudience_v1 object

    Raises:
        AttributeError: Unknown alias

    Returns:
        set -- Audience to send email to
    """
    audience = set()

    aliases = to.get("aliases")
    if aliases:
        for alias in aliases:
            if alias == "all-users":
                users = queries.get_users()
                to["users"] = users
            elif alias == "all-service-owners":
                services = queries.get_apps()
                to["services"] = services
            else:
                raise AttributeError(f"unknown alias: {alias}")

    services = to.get("services")
    if services:
        for service in services:
            service_owners = service.get("serviceOwners")
            if not service_owners:
                continue

            for service_owner in service_owners:
                audience.add(service_owner["email"])

    # TODO: implement clusters and namespaces

    aws_accounts = to.get("aws_accounts")
    if aws_accounts:
        for account in aws_accounts:
            account_owners = account.get("accountOwners")
            if not account_owners:
                continue

            for account_owner in account_owners:
                audience.add(account_owner["email"])

    roles = to.get("roles")
    if roles:
        for role in roles:
            users = role.get("users")
            if not users:
                continue

            for user in users:
                audience.add(user["org_username"])

    users = to.get("users")
    if users:
        for user in users:
            audience.add(user["org_username"])

    return audience


@defer
def run(dry_run, defer=None):
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    state = init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader)
    defer(state.cleanup)
    emails = queries.get_app_interface_emails()
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
    email_names = {e["name"] for e in emails}
    if len(emails) != len(email_names):
        logging.error("email names must be unique.")
        sys.exit(1)

    emails_to_send = [e for e in emails if not state.exists(e["name"])]
    for email in emails_to_send:
        logging.info(["send_email", email["name"], email["subject"]])

        if not dry_run:
            names = collect_to(email["to"])
            subject = email["subject"]
            body = email["body"]
            smtp_client.send_mail(names, subject, body)
            state.add(email["name"])
