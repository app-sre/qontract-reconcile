import sys
import logging

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.smtp_client import SmtpClient
import reconcile.queries as queries

from reconcile.utils.state import State
from reconcile.utils.gpg import gpg_encrypt

QONTRACT_INTEGRATION = 'requests-sender'


MESSAGE_TEMPLATE = """
Hello,

Following your credentials request in app-interface,
PFA the requested information.

The credentials are encrypted with your public gpg key.

Details:

Request name: {}
Credentials name: {}
Encrypted credentials:

{}

"""


def get_encrypted_credentials(credentials_name, user, settings, smtp_client):
    credentials_map = settings['credentials']
    credentials_map_item = \
        [c for c in credentials_map if c['name'] == credentials_name]
    if len(credentials_map_item) != 1:
        return None
    secret = credentials_map_item[0]['secret']
    secret_reader = SecretReader(settings=settings)
    credentials = secret_reader.read(secret)
    recepient = smtp_client.get_recipient(user['org_username'])
    public_gpg_key = user['public_gpg_key']
    encrypted_credentials = \
        gpg_encrypt(credentials, recepient, public_gpg_key)

    return encrypted_credentials


def run(dry_run):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    smtp_client = SmtpClient(settings=settings)
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        settings=settings
    )
    credentials_requests = queries.get_credentials_requests()

    # validate no 2 requests have the same name
    credentials_requests_names = {r['name'] for r in credentials_requests}
    if len(credentials_requests) != len(credentials_requests_names):
        logging.error('request names must be unique.')
        sys.exit(1)

    error = False

    credentials_requests_to_send = \
        [r for r in credentials_requests if not state.exists(r['name'])]
    for credentials_request_to_send in credentials_requests_to_send:
        user = credentials_request_to_send['user']
        org_username = user['org_username']
        public_gpg_key = user.get('public_gpg_key')
        credentials_name = credentials_request_to_send['credentials']
        if not public_gpg_key:
            error = True
            logging.error(
                f"user {org_username} does not have a public gpg key")
            continue
        logging.info(['send_credentials', org_username, credentials_name])

        if not dry_run:
            request_name = credentials_request_to_send['name']
            names = [org_username]
            subject = request_name
            encrypted_credentials = get_encrypted_credentials(credentials_name,
                                                            user, settings,
                                                            smtp_client)
            if not encrypted_credentials:
                error = True
                logging.error(
                    f"could not get encrypted credentials {credentials_name}")
                continue
            body = MESSAGE_TEMPLATE.format(
                request_name, credentials_name, encrypted_credentials)
            smtp_client.send_mail(names, subject, body)
            state.add(request_name)

    if error:
        sys.exit(1)
