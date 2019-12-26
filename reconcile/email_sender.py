import sys
import logging

# import utils.gql as gql
import utils.smtp_client as smtp_client
import reconcile.queries as queries

from utils.state import State

QONTRACT_INTEGRATION = 'email-sender'


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

    for alias in to.get('aliases') or []:
        # gql = gql.get_api()
        if alias == 'all-users':
            pass
        elif alias == 'all-service-owners':
            pass
        else:
            raise AttributeError(f"unknown alias: {alias}")

    for service in to.get('services') or []:
        for service_owner in service.get('serviceOwners', []):
            audience.add(service_owner['email'])

    for cluster in to.get('clusters') or []:
        # TODO: implement this
        pass

    for namespace in to.get('namespaces') or []:
        # TODO: implement this
        pass

    for account in to.get('aws_accounts') or []:
        # TODO: implement this
        pass

    for role in to.get('roles') or []:
        for user in role.get('users') or []:
            audience.add(user['org_username'])

    for user in to.get('users') or []:
        audience.add(user['org_username'])

    return audience


def run(dry_run=False):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        settings=settings
    )
    emails = queries.get_app_interface_emails()

    # validate no 2 emails have the same name
    email_names = set([e['name'] for e in emails])
    if len(emails) != len(email_names):
        logging.error('email names must be unique.')
        sys.exit(1)

    emails_to_send = [e for e in emails if not state.exists(e['name'])]

    # validate that there is only 1 mail to send
    # this is a safety net in case state is lost
    # the solution to such loss is to delete all emails from app-interface
    if len(emails_to_send) > 1:
        logging.error('can only send one email at a time.')
        sys.exit(1)

    for email in emails_to_send:
        logging.info(['send_email', email['name'], email['subject']])

        if not dry_run:
            state.add(email['name'])

            names = collect_to(email['to'])
            subject = email['subject']
            body = email['body']
            smtp_client.send_mail(names, subject, body, settings=settings)
