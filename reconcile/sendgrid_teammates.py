import logging

import sendgrid

import reconcile.queries as queries
from reconcile.utils.secret_reader import SecretReader

LOG = logging.getLogger(__name__)
QONTRACT_INTEGRATION = 'sendgrid_teammates'


class Teammate:
    def __init__(self, email, pending=False):
        self.email = email
        self.pending = pending


def fetch_desired_state(users):
    desired_state = {}
    for user in users:
        roles = user.get('roles', [])
        for role in roles:
            sendgrid_accounts = role.get('sendgrid_accounts') or []
            for sg_account in sendgrid_accounts:
                desired_state.setdefault(sg_account['name'], [])
                t = Teammate(f"{user['org_username']}@redhat.com")
                desired_state[sg_account['name']].append(t)

    return desired_state


def fetch_current_state(sg_client):
    state = []

    # pending invites
    invites = sg_client.teammates.pending.get().to_dict['result']
    for invite in invites:
        t = Teammate(invite['email'], pending=True)
        state.append(t)

    # current teammates
    teammates = sg_client.teammates.get().to_dict['result']
    for teammate in teammates:
        if teammate['user_type'] == 'owner':
            # we want to ignore the root account (owner account)
            continue

        t = Teammate(teammate['email'], pending=False)
        state.append(t)

    return state


def act(dry_run, sg_client, desired_state, current_state):
    desired_emails = [e.email for e in desired_state]
    current_emails = [e.email for e in current_state]

    for user in current_emails:
        if user.email not in desired_emails:
            LOG.info(['delete', user.email])

    for user in desired_state:
        if user.email not in current_emails:
            # ignore pending users
            if user.pending:
                continue

            LOG.info(['invite', user.email])

            if not dry_run:
                req = {
                    'email': user.email,
                    'scopes': [],
                    'is_admin': True,
                }

                response = sg_client.teammates.post(request_body=req)
                if int(response.status_code / 100) != 2:
                    LOG.error(['error inviting user',
                               response.body.decode('utf-8')])


def run(dry_run):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    users = queries.get_roles()
    desired_state_all = fetch_desired_state(users)

    sendgrid_accounts = queries.get_sendgrid_accounts()
    for sg_account in sendgrid_accounts:
        token = secret_reader.read(sg_account['token'])
        sg_client = sendgrid.SendGridAPIClient(api_key=token).client

        current_state = fetch_current_state(sg_client)
        desired_state = desired_state_all.get(sg_account['name'], [])

        act(dry_run, sg_client, desired_state, current_state)
