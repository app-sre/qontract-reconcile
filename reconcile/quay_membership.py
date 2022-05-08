import logging
import sys

from reconcile.utils import gql
from reconcile.utils import expiration

from reconcile.utils.aggregated_list import (
    AggregatedList,
    AggregatedDiffRunner,
    RunnerException,
)
from reconcile.quay_base import get_quay_api_store
from reconcile.status import ExitCodes
from reconcile.utils.quay_api import QuayTeamNotFoundException

QUAY_ORG_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      name
      quay_username
    }
    bots {
      name
      quay_username
    }
    permissions {
      service
      ...on PermissionQuayOrgTeam_v1 {
        quayOrg {
          name
          instance {
            name
          }
        }
        team
      }
    }
    expirationDate
  }
}
"""

QONTRACT_INTEGRATION = "quay-membership"


def process_permission(permission):
    """Returns a new permission object with the right keys

    State needs these fields: service, org, team.

    But the input (coming from QUAY_ORG_QUERY) will have:
    service, quayOrg, team
    """

    return {
        "service": permission["service"],
        "team": permission["team"],
        "org": (
            permission["quayOrg"]["instance"]["name"],
            permission["quayOrg"]["name"],
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


def fetch_desired_state():
    gqlapi = gql.get_api()
    roles = expiration.filter(gqlapi.query(QUAY_ORG_QUERY)["roles"])

    state = AggregatedList()

    for role in roles:
        permissions = [
            process_permission(p)
            for p in role["permissions"]
            if p.get("service") == "quay-membership"
        ]

        if permissions:
            members = []

            for user in role["users"] + role["bots"]:
                quay_username = user.get("quay_username")
                if quay_username:
                    members.append(quay_username)

            for p in permissions:
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
