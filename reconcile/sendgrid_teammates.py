from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import sendgrid
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.gql_definitions.sendgrid_teammates.accounts import (
    query as accounts_query,
)
from reconcile.gql_definitions.sendgrid_teammates.roles import (
    RoleV1,
    UserV1,
)
from reconcile.gql_definitions.sendgrid_teammates.roles import (
    query as roles_query,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.membershipsources.resolver import (
    resolve_role_members,
)
from reconcile.utils.secret_reader import SecretReader

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

LOG = logging.getLogger(__name__)
QONTRACT_INTEGRATION = "sendgrid_teammates"


class SendGridAPIError(Exception):
    pass


class Teammate:
    def __init__(
        self, email: str, pending_token: str | None = None, username: str | None = None
    ) -> None:
        self.email = email
        self.username = username or email.split("@", maxsplit=1)[0]
        self.pending_token = pending_token

    @property
    def pending(self) -> bool:
        return bool(self.pending_token)


def get_roles(query_func: Callable) -> list[RoleV1]:
    """Fetch SendGrid roles with their effective user memberships."""
    return resolve_role_members(
        [
            role
            for role in roles_query(query_func=query_func).roles or []
            if role.sendgrid_accounts
        ],
        user_cls=UserV1,
        query_func=query_func,
    )


def fetch_desired_state(
    roles: Iterable[RoleV1],
) -> dict[str, list[Teammate]]:
    desired_state: dict[str, list[Teammate]] = {}
    for role in roles:
        for sg_account in role.sendgrid_accounts or []:
            members = desired_state.setdefault(sg_account.name, [])
            for user in role.users:
                if (username := user.org_username) and not any(
                    member.email == f"{username}@redhat.com" for member in members
                ):
                    members.append(Teammate(f"{username}@redhat.com"))

    return desired_state


@retry()
def fetch_current_state(sg_client: sendgrid.SendGridAPIClient) -> list[Teammate]:
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


def raise_if_error(response: Any) -> None:
    """
    Raises an SendGridAPIError if the request has returned an error
    """
    if response.status_code >= 300:
        raise SendGridAPIError(response.body.decode("utf-8"))


def act(
    dry_run: bool,
    sg_client: sendgrid.SendGridAPIClient,
    desired_state: Iterable[Teammate],
    current_state: Iterable[Teammate],
) -> bool:
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


def run(dry_run: bool) -> None:
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    gqlapi = gql.get_api()
    roles = get_roles(query_func=gqlapi.query)
    desired_state_all = fetch_desired_state(roles)

    sendgrid_accounts = accounts_query(gqlapi.query).accounts or []
    for sg_account in sendgrid_accounts:
        token = secret_reader.read_secret(sg_account.token)
        sg_client = sendgrid.SendGridAPIClient(api_key=token).client

        current_state = fetch_current_state(sg_client)
        desired_state = desired_state_all.get(sg_account.name, [])

        error = act(dry_run, sg_client, desired_state, current_state)
        if error:
            sys.exit(ExitCodes.ERROR)
