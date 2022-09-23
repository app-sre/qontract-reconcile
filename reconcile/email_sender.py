import sys
import logging

from reconcile.utils.smtp_client import SmtpClient
from reconcile import queries

from reconcile.utils.state import State

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


def run(dry_run):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )
    emails = queries.get_app_interface_emails()
    smtp_client = SmtpClient(settings=settings)
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
