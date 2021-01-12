import logging

import sendgrid

import reconcile.queries as queries
import reconcile.utils.gql as gql
from reconcile.utils.secret_reader import SecretReader


QONTRACT_INTEGRATION = 'sendgrid_teammates'

def fetch_current_state(sg_client):
    # pending invites
    invites = sg_client.teammates.pending.get().to_dict['result']
    for invite in invites:
        print(invite['email'])

def run(dry_run):
    settings = queries.get_app_interface_settings()
    gqlapi = gql.get_api()
    secret_reader = SecretReader(settings=settings)

    sendgrid_accounts = queries.get_sendgrid_accounts()

    for sg_account in sendgrid_accounts:
        token = secret_reader.read(sg_account['token'])
        sg_client = sendgrid.SendGridAPIClient(api_key=token)

        current_state = fetch_current_state(sg_client.client)
