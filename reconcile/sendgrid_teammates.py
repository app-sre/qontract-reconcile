import logging
import sys

import sendgrid
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.secret_reader import SecretReader

LOG = logging.getLogger(__name__)
QONTRACT_INTEGRATION = "sendgrid_teammates"


class SendGridAPIError(Exception):
    pass


class Teammate:
    def __init__(self, email, pending_token=None, username=None):
        self.email = email
        self.username = username or email.split("@")[0]
        self.pending_token = pending_token

    @property
    def pending(self):
        return bool(self.pending_token)


def fetch_desired_state(users):
    desired_state = {}
    for user in users:
        roles = user.get("roles") or []
        for role in roles:
            sendgrid_accounts = role.get("sendgrid_accounts") or []
            for sg_account in sendgrid_accounts:
                desired_state.setdefault(sg_account["name"], [])
                t = Teammate(f"{user['org_username']}@redhat.com")
                desired_state[sg_account["name"]].append(t)

    return desired_state


@retry()
def fetch_current_state(sg_client):
    state = []
    limit = 100

    # pending invites
    offset = 0
    while True:
        invites = sg_client.teammates.pending.get(
            query_params={"limit": limit, "offset": offset}
        ).to_dict["result"]
        if not invites:
            break
        for invite in invites:
            t = Teammate(invite["email"], pending_token=invite["token"])
            state.append(t)
        offset += limit

    # current teammates
    offset = 0
    while True:
        teammates = sg_client.teammates.get(
            query_params={"limit": limit, "offset": offset}
        ).to_dict["result"]
        if not teammates:
            break
        for teammate in teammates:
            if teammate["user_type"] == "owner":
                # we want to ignore the root account (owner account)
                continue

            t = Teammate(teammate["email"], username=teammate["username"])
            state.append(t)
        offset += limit

    return state


def raise_if_error(response):
    """
    Raises an SendGridAPIError if the request has returned an error
    """
    if response.status_code >= 300:
        raise SendGridAPIError(response.body.decode("utf-8"))


def act(dry_run, sg_client, desired_state, current_state):
    """
    Reconciles current state with desired state.

    :return: true if there has been an error
    :rtype: bool
    """

    desired_emails = [e.email for e in desired_state]
    current_emails = [e.email for e in current_state]

    error = False

    for user in current_state:
        if user.email not in desired_emails:
            LOG.info(["delete", user.email])
            if not dry_run:
                if user.pending:
                    delete_method = sg_client.teammates.pending
                    identifier = user.pending_token
                else:
                    delete_method = sg_client.teammates
                    identifier = user.username

                response = delete_method._(identifier).delete()

                try:
                    raise_if_error(response)
                except SendGridAPIError as e:
                    error = True
                    LOG.error(["error deleting user", str(e)])

    for user in desired_state:
        if user.email not in current_emails:
            # ignore pending users
            if user.pending:
                continue

            LOG.info(["invite", user.email])

            if not dry_run:
                req = {
                    "email": user.email,
                    "scopes": [],
                    "is_admin": True,
                }

                response = sg_client.teammates.post(request_body=req)

                try:
                    raise_if_error(response)
                except SendGridAPIError as e:
                    error = True
                    LOG.error(["error inviting user", str(e)])

    return error


def run(dry_run):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    users = queries.get_roles(aws=False, saas_files=False, sendgrid=True)
    desired_state_all = fetch_desired_state(users)

    sendgrid_accounts = queries.get_sendgrid_accounts()
    for sg_account in sendgrid_accounts:
        token = secret_reader.read(sg_account["token"])
        sg_client = sendgrid.SendGridAPIClient(api_key=token).client

        current_state = fetch_current_state(sg_client)
        desired_state = desired_state_all.get(sg_account["name"], [])

        error = act(dry_run, sg_client, desired_state, current_state)
        if error:
            sys.exit(ExitCodes.ERROR)
