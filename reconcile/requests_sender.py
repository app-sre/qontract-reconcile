import sys
import logging
from subprocess import CalledProcessError

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.smtp_client import (
    DEFAULT_SMTP_TIMEOUT,
    SmtpClient,
    get_smtp_server_connection,
)
from reconcile import queries, typed_queries

from reconcile.utils.state import State
from reconcile.utils.gpg import gpg_encrypt


QONTRACT_INTEGRATION = "requests-sender"


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


def get_encrypted_credentials(credentials_name, user, settings):
    credentials_map = settings["credentials"]
    credentials_map_item = [c for c in credentials_map if c["name"] == credentials_name]
    if len(credentials_map_item) != 1:
        return None
    secret = credentials_map_item[0]["secret"]
    secret_reader = SecretReader(settings=settings)
    credentials = secret_reader.read(secret)
    public_gpg_key = user["public_gpg_key"]
    encrypted_credentials = gpg_encrypt(credentials, public_gpg_key)

    return encrypted_credentials


def run(dry_run):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    smtp_settings = typed_queries.smtp.settings()
    smtp_client = SmtpClient(
        server=get_smtp_server_connection(
            secret_reader=SecretReader(settings=settings),
            secret=smtp_settings.credentials,
        ),
        mail_address=smtp_settings.mail_address,
        timeout=smtp_settings.timeout or DEFAULT_SMTP_TIMEOUT,
    )
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )
    credentials_requests = queries.get_credentials_requests()

    # validate no 2 requests have the same name
    credentials_requests_names = {r["name"] for r in credentials_requests}
    if len(credentials_requests) != len(credentials_requests_names):
        logging.error("request names must be unique.")
        sys.exit(1)

    error = False

    credentials_requests_to_send = [
        r for r in credentials_requests if not state.exists(r["name"])
    ]
    for credentials_request_to_send in credentials_requests_to_send:
        try:
            user = credentials_request_to_send["user"]
            credentials_name = credentials_request_to_send["credentials"]
            org_username = user["org_username"]
            logging.info(["send_credentials", org_username, credentials_name])

            request_name = credentials_request_to_send["name"]
            names = [org_username]
            subject = request_name
            encrypted_credentials = get_encrypted_credentials(
                credentials_name, user, settings
            )
            if not dry_run:
                body = MESSAGE_TEMPLATE.format(
                    request_name, credentials_name, encrypted_credentials
                )
                smtp_client.send_mail(names, subject, body)
                state.add(request_name)
        except KeyError:
            logging.exception(
                f"Bad user details for {org_username} - {credentials_name}"
            )
            error = True
        except CalledProcessError as e:
            logging.exception(
                f"Failed to handle GPG key for {org_username} "
                f"({credentials_name}): {e.stdout}"
            )
            error = True

    if error:
        sys.exit(1)
