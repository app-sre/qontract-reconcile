import sys
import logging

from reconcile.utils import gql

from reconcile.status import ExitCodes
from reconcile.quay_base import get_quay_api_store


QUAY_REPOS_QUERY = """
{
  apps: apps_v1 {
    name
    quayRepos {
      org {
        name
        managedRepos
        automationToken {
          path
          field
          version
          format
        }
        instance {
          name
        }
      }
      teams {
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
        role
      }
      items {
        name
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = "quay-permissions"


def run(dry_run):
    gqlapi = gql.get_api()
    apps = gqlapi.query(QUAY_REPOS_QUERY)["apps"]
    quay_api_store = get_quay_api_store()
    error = False
    for app in apps:
        quay_repo_configs = app.get("quayRepos")
        if not quay_repo_configs:
            continue
        for quay_repo_config in quay_repo_configs:
            instance_name = quay_repo_config["org"]["instance"]["name"]
            org_name = quay_repo_config["org"]["name"]
            org_key = (instance_name, org_name)

            if not quay_repo_config["org"]["managedRepos"]:
                logging.error(
                    f"[{app['name']}] Can not manage repo permissions in {org_name} "
                    "since managedRepos is set to false."
                )
                error = True
                continue

            # processing quayRepos section
            logging.debug(["app", app["name"], instance_name, org_name])

            quay_api = quay_api_store[org_key]["api"]
            teams = quay_repo_config.get("teams")
            if not teams:
                continue
            repos = quay_repo_config["items"]
            for repo in repos:
                repo_name = repo["name"]

                # processing repo section
                logging.debug(["repo", repo_name])

                for team in teams:
                    permissions = team["permissions"]
                    role = team["role"]
                    for permission in permissions:
                        if permission["service"] != "quay-membership":
                            logging.warning(
                                "wrong service kind, " "should be quay-membership"
                            )
                            continue

                        perm_org_key = (
                            permission["quayOrg"]["instance"]["name"],
                            permission["quayOrg"]["name"],
                        )

                        if perm_org_key != org_key:
                            logging.warning(f"wrong org, should be {org_key}")
                            continue

                        team_name = permission["team"]

                        # processing team section
                        logging.debug(["team", team_name])
                        try:
                            current_role = quay_api.get_repo_team_permissions(
                                repo_name, team_name
                            )
                            if current_role != role:
                                logging.info(
                                    ["update_role", org_key, repo_name, team_name, role]
                                )
                                if not dry_run:
                                    quay_api.set_repo_team_permissions(
                                        repo_name, team_name, role
                                    )
                        except Exception:
                            error = True
                            logging.exception(
                                "could not manage repo permissions: "
                                f"repo name: {repo_name}, "
                                f"team name: {team_name}"
                            )

    if error:
        sys.exit(ExitCodes.ERROR)
