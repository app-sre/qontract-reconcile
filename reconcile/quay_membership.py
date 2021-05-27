import logging
import sys

import reconcile.utils.gql as gql

from reconcile.utils.aggregated_list import (AggregatedList,
                                             AggregatedDiffRunner,
                                             RunnerException)
from reconcile.quay_base import get_quay_api_store
from reconcile.status import ExitCodes


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
  }
}
"""

QONTRACT_INTEGRATION = 'quay-membership'


def process_permission(permission):
    """Returns a new permission object with the right keys

    State needs these fields: service, org, team.

    But the input (coming from QUAY_ORG_QUERY) will have:
    service, quayOrg, team
    """

    return {
        'service': permission['service'],
        'team': permission['team'],
        'org': (permission['quayOrg']['instance']['name'],
                permission['quayOrg']['name'])
    }


def fetch_current_state(quay_api_store):
    state = AggregatedList()

    for org_key, org_data in quay_api_store.items():
        quay_api = org_data['api']
        teams = org_data['teams']
        if not teams:
            continue
        for team in teams:
            members = quay_api.list_team_members(team)
            state.add({
                'service': 'quay-membership',
                'org': org_key,
                'team': team
            }, members)
    return state


def fetch_desired_state():
    gqlapi = gql.get_api()
    result = gqlapi.query(QUAY_ORG_QUERY)

    state = AggregatedList()

    for role in result['roles']:
        permissions = [
            process_permission(p)
            for p in role['permissions']
            if p.get('service') == 'quay-membership'
        ]

        if permissions:
            members = []

            def append_quay_username_members(member):
                quay_username = member.get('quay_username')
                if quay_username:
                    members.append(quay_username)

            for user in role['users']:
                append_quay_username_members(user)

            for bot in role['bots']:
                append_quay_username_members(bot)

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
            quay_api = self.quay_api_store[org]['api']
            for member in items:
                logging.info([label, member, org, team])
                user_exists = quay_api.user_exists(member)
                if user_exists:
                    if not self.dry_run:
                        quay_api.add_user_to_team(member, team)
                else:
                    missing_users = True
                    logging.error(f'quay user {member} does not exist.')

            # This will be evaluated by AggregatedDiffRunner.run(). The happy
            # case is to return True: no missing users
            return not missing_users

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
                quay_api = self.quay_api_store[org]['api']
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

    # Ensure all quay org/teams are declared as dependencies:
    # any item that appears in `diff['insert']` means that it's not listed
    # in a `/dependencies/quay-org-1.yml` datafile.
    if len(diff['insert']) > 0:
        unknown_teams = [
            "- {}/{}".format(
                item["params"]["org"],
                item["params"]["team"],
            )
            for item in diff['insert']
        ]

        raise RunnerException((
            "Unknown quay/org/team found:\n"
            "{}"
        ).format("\n".join(unknown_teams))
        )

    # Run actions
    runner_action = RunnerAction(dry_run, quay_api_store)
    runner = AggregatedDiffRunner(diff)

    runner.register("update-insert", runner_action.add_to_team())
    runner.register("update-delete", runner_action.del_from_team())
    runner.register("delete", runner_action.del_from_team())

    status = runner.run()
    if not status:
        sys.exit(ExitCodes.ERROR)
