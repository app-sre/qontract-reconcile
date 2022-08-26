import logging
import sys
from typing import Sequence, Union, cast

from reconcile.gql_definitions.quay_membership import quay_membership
from reconcile.gql_definitions.quay_membership.quay_membership import (
    BotV1,
    PermissionQuayOrgTeamV1,
    RoleV1,
    UserV1,
)
from reconcile.quay_base import get_quay_api_store
from reconcile.status import ExitCodes
from reconcile.utils import expiration, gql
from reconcile.utils.aggregated_list import (
    AggregatedDiffRunner,
    AggregatedList,
    RunnerException,
)
from reconcile.utils.helpers import filter_null
from reconcile.utils.quay_api import QuayTeamNotFoundException

QONTRACT_INTEGRATION = "quay-membership"


def get_permissions_for_quay_membership() -> list[PermissionQuayOrgTeamV1]:
    query_data = quay_membership.query(query_func=gql.get_api().query)

    if not query_data.permissions:
        return []
    return [p for p in query_data.permissions if isinstance(p, PermissionQuayOrgTeamV1)]


def process_permission(permission: PermissionQuayOrgTeamV1):
    """Returns a new permission object with the right keys

    State needs these fields: service, org, team.

    But the input (coming from QUAY_ORG_QUERY) will have:
    service, quayOrg, team
    """

    return {
        "service": permission.service,
        "team": permission.team,
        "org": (
            permission.quay_org.instance.name,
            permission.quay_org.name,
        ),
    }


def fetch_current_state(quay_api_store):
    state = AggregatedList()

    for org_key, org_data in quay_api_store.items():
        quay_api = org_data["api"]
        teams = org_data["teams"]
        if not teams:
            continue
        for team in teams:
            try:
                members = quay_api.list_team_members(team)
            except QuayTeamNotFoundException:
                logging.warning(
                    "Attempted to list members for team %s in "
                    "org %s/%s, but it doesn't exist",
                    team,
                    org_key.instance,
                    org_key.org_name,
                )
            else:
                # Teams are only added to the state if they exist so that
                # there is a proper diff between the desired and current state.
                state.add(
                    {"service": "quay-membership", "org": org_key, "team": team},
                    members,
                )
    return state


def get_usernames(users: Sequence[Union[UserV1, BotV1]]) -> list[str]:
    return [u.quay_username for u in users if u.quay_username]


def fetch_desired_state():
    permissions = get_permissions_for_quay_membership()
    state = AggregatedList()

    for permission in permissions:
        p = process_permission(permission)
        members: list[str] = []
        roles: list[RoleV1] = filter_null(permission.roles)
        filtered_roles: list[RoleV1] = [
            cast(RoleV1, r) for r in expiration.filter(roles)
        ]
        for role in filtered_roles:
            users: list[UserV1] = filter_null(role.users)
            bots: list[BotV1] = filter_null(role.bots)
            members += get_usernames(users) + get_usernames(bots)

        state.add(p, members)

    return state


class RunnerAction:
    def __init__(self, dry_run, quay_api_store):
        self.dry_run = dry_run
        self.quay_api_store = quay_api_store

    def add_to_team(self):
        label = "add_to_team"

        def action(params, items):
            org = params["org"]
            team = params["team"]

            missing_users = False
            quay_api = self.quay_api_store[org]["api"]
            for member in items:
                logging.info([label, member, org, team])
                user_exists = quay_api.user_exists(member)
                if user_exists:
                    if not self.dry_run:
                        quay_api.add_user_to_team(member, team)
                else:
                    missing_users = True
                    logging.error(f"quay user {member} does not exist.")

            # This will be evaluated by AggregatedDiffRunner.run(). The happy
            # case is to return True: no missing users
            return not missing_users

        return action

    def create_team(self):
        """
        Create an empty team in Quay. This method avoids adding users to the
        new team. add_to_team() will handle updating the member list the
        next time run() is executed, while keeping this action very simple.
        """
        label = "create_team"

        def action(params, items):
            org = params["org"]
            team = params["team"]

            # Ensure all quay org/teams are declared as dependencies in a
            # `/dependencies/quay-org-1.yml` datafile.
            if team not in self.quay_api_store[org]["teams"]:
                raise RunnerException(
                    f"Quay team {team} is not defined as a "
                    f"managedTeam in the {org} org."
                )

            logging.info([label, org, team])

            if not self.dry_run:
                quay_api = self.quay_api_store[org]["api"]
                quay_api.create_or_update_team(team)

            return True

        return action

    def del_from_team(self):
        label = "del_from_team"

        def action(params, items):
            org = params["org"]
            team = params["team"]

            if self.dry_run:
                for member in items:
                    logging.info([label, member, org, team])
            else:
                quay_api = self.quay_api_store[org]["api"]
                for member in items:
                    logging.info([label, member, org, team])
                    quay_api.remove_user_from_team(member, team)

            return True

        return action


def run(dry_run):
    quay_api_store = get_quay_api_store()

    current_state = fetch_current_state(quay_api_store)
    desired_state = fetch_desired_state()

    # calculate diff
    diff = current_state.diff(desired_state)
    logging.debug("State diff: %s", diff)

    # Run actions
    runner_action = RunnerAction(dry_run, quay_api_store)
    runner = AggregatedDiffRunner(diff)

    runner.register("insert", runner_action.create_team())
    runner.register("update-insert", runner_action.add_to_team())
    runner.register("update-delete", runner_action.del_from_team())
    runner.register("delete", runner_action.del_from_team())

    status = runner.run()
    if not status:
        sys.exit(ExitCodes.ERROR)
