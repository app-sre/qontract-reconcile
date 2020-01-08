import logging
import reconcile.queries as queries
import utils.gql as gql
import utils.secret_reader as secret_reader

from reconcile.github_users import init_github
from utils.sentry_client import SentryClient


SENTRY_PROJECTS_QUERY = """
{
  apps: apps_v1 {
    sentryProjects {
      team {
        name
        instance {
          consoleUrl
        }
      }
      projects {
        name
        description
        email_prefix
        platform
        sensitive_fields
        safe_fields
        auto_resolve_age
        allowed_domains
      }
    }
  }
}
"""

SENTRY_USERS_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      name
      github_username
    }
    bots {
      name
      github_username
    }
    sentry_teams {
      name
      instance {
        consoleUrl
        automationToken {
          path
          field
          format
          version
        }
      }
    }
  }
}
"""

SENTRY_TEAMS_QUERY = """
{
  teams: sentry_teams_v1 {
    name
    instance {
      consoleUrl
      automationToken {
        path
        field
        format
        version
      }
    }
  }
}
"""

SENTRY_INSTANCES_QUERY = """
{
  instances: sentry_instances_v1 {
    consoleUrl
    automationToken {
      path
      field
      format
      version
    }
    adminUser {
      path
      field
      format
      version
    }
  }
}
"""


class SentryState:
    def __init__(self):
        # Map of user:teams[]
        self.users = {}
        # List of team names
        self.teams = []
        # Map of team:projects_config[]
        self.projects = {}

    def init_users(self, users):
        self.users = users

    def init_users_from_desired_state(self, users):
        # Input is in the form of team:members[]
        for team in users.keys():
            for user in users[team]:
                if team not in self.users.keys():
                    self.users[user] = [team]
                else:
                    self.users[user].append(team)

    def init_projects_from_current_state(self, client, projects):
        # Input is in the form of project:teams[]
        for project in projects.keys():
            for team in projects[project]:
                # TODO: Retrieve project and store relevant config
                p = client.get_project(project)
                pdata = {
                    "name": p['name'],
                    "email_prefix": p['subjectPrefix'],
                    "platform": p['platform']
                }

                optional_fields = {
                    "sensitiveFields": "sensitive_fields",
                    "safeFields": "safe_fields",
                    "resolveAge": "auto_resolve_age",
                    "allowedDomains": "allowed_domains",
                }
                for k, v in optional_fields.items():
                    if k in p.keys():
                        pdata[v] = p[k]

                if team not in self.projects.keys():
                    self.projects[team] = [pdata]
                else:
                    self.projects[team].append(pdata)

    def init_projects(self, projects):
        self.projects = projects

    def init_teams(self, teams):
        self.teams = teams


class SentryReconciler:
    def __init__(self, client, dry_run):
        self.client = client
        self.dry_run = dry_run

    def reconcile(self, current, desired):
        # Reconcile the teams first
        for team in current.teams:
            if team not in desired.teams:
                logging.info(["delete_team", team, self.client.host])
                if not self.dry_run:
                    self.client.delete_team(team)

        for team in desired.teams:
            if team not in current.teams:
                logging.info(["create_team", team, self.client.host])
                if not self.dry_run:
                    self.client.create_team(team)

        # Reconcile users
        for user in current.users.keys():
            if user not in desired.users.keys():
                logging.info(["delete_user", user, self.client.host])
                if not self.dry_run:
                    self.client.delete_user(user)

        for user in desired.users.keys():
            teams = desired.users[user]
            if user not in current.users.keys():
                logging.info(
                    ["add_user", user, ",".join(teams), self.client.host])
                if not self.dry_run:
                    self.client.create_user(user, "member", teams)
            else:
                logging.info(["team_membership", user,
                              ",".join(teams), self.client.host])
                if not self.dry_run:
                    self.client.set_user_teams(user, teams)
                logging.info(["user_role", user, "member", self.client.host])
                if not self.dry_run:
                    self.client.change_user_role(user, "member")

        # Reconcile projects
        for projects in current.projects.values():
            for current_project in projects:
                if project_in_project_list(current_project,
                                           desired.projects.values()):
                    continue
                project_name = current_project['name']
                logging.info(
                    ["delete_project", project_name, self.client.host])
                if not self.dry_run:
                    self.client.delete_project(project_name)

        for team in desired.projects.keys():
            for desired_project in desired.projects[team]:
                project_name = desired_project['name']
                if not project_in_project_list(desired_project,
                                               current.projects.values()):
                    logging.info(
                        ["add_project", project_name, self.client.host])
                    if not self.dry_run:
                        self.client.create_project(team, project_name)
                logging.info(
                    ["update_project", desired_project, self.client.host])
                try:
                    self.client.validate_project_options(desired_project)
                except Exception as e:
                    logging.error(["update_project", str(e), self.client.host])
                    continue

                if not self.dry_run:
                    self.client.update_project(project_name, desired_project)


def project_in_project_list(project, list):
    for projects in list:
        for p in projects:
            if p['name'] == project['name']:
                return True
    return False


def fetch_current_state(client, ignore_users):
    state = SentryState()

    # Retrieve all the teams
    sentry_teams = client.get_teams()
    teams = [team['slug'] for team in sentry_teams]
    state.init_teams(teams)

    # Retrieve the projects and the teams associated with them
    sentry_projects = client.get_projects()
    projects = {}
    for sentry_project in sentry_projects:
        project_slug = sentry_project['slug']
        if project_slug == "internal":
            # This project can't be deleted
            continue
        project = client.get_project(project_slug)
        project_teams = []
        for team in project['teams']:
            project_teams.append(team['slug'])
        projects[project_slug] = project_teams
    state.init_projects_from_current_state(client, projects)

    # Retrieve the users and the teams they are part of
    sentry_users = client.get_users()
    users = {}
    for sentry_user in sentry_users:
        user_name = sentry_user['email']
        if user_name in ignore_users:
            continue
        user = client.get_user(user_name)
        teams = []
        for team in user['teams']:
            teams.append(team)
        users[user_name] = teams
    state.init_users(users)
    return state


def fetch_desired_state(gqlapi, sentry_instance):
    state = SentryState()

    # Query for users that should be in sentry
    team_members = {}
    result = gqlapi.query(SENTRY_USERS_QUERY)
    github = init_github()
    for role in result['roles']:
        if role['sentry_teams'] is None:
            continue

        for team in role['sentry_teams']:
            # Users that should exist
            members = []

            def append_github_username_members(member):
                github_username = member.get('github_username')
                if github_username:
                    user_info = github.get_user(login=github_username)
                    email = user_info.email
                    if email is not None:
                        members.append(email)

            for user in role['users']:
                append_github_username_members(user)

            for bot in role['bots']:
                append_github_username_members(bot)

            # Only add users if the team they are a part of is in the same
            # senry instance we are querying for information
            if team['instance']['consoleUrl'] == sentry_instance['consoleUrl']:
                if team['name'] not in team_members.keys():
                    team_members[team['name']] = members
                else:
                    team_members[team['name']].extend(members)
    state.init_users_from_desired_state(team_members)

    # Query for teams that should be in sentry
    result = gqlapi.query(SENTRY_TEAMS_QUERY)
    teams = []
    for team in result['teams']:
        if team['instance']['consoleUrl'] == sentry_instance['consoleUrl']:
            if team in teams:
                logging.error(["team_exists", team])
                continue
            teams.append(team["name"])
    state.init_teams(teams)

    # Query for projects that should be in sentry
    result = gqlapi.query(SENTRY_PROJECTS_QUERY)
    projects = {}
    for app in result['apps']:
        sentry_projects = app.get('sentryProjects')

        if sentry_projects is None:
            continue

        for sentry_project in sentry_projects:
            if sentry_project['team']['instance']['consoleUrl'] != \
               sentry_instance['consoleUrl']:
                continue

            team = sentry_project['team']['name']
            team_projects = []
            for project_config in sentry_project['projects']:
                if project_in_project_list(project_config, projects.values()):
                    logging.error(["project_exists", project_config['name']])
                    continue

                config = {}
                for field in project_config.keys():
                    if project_config[field] is not None:
                        config[field] = project_config[field]
                team_projects.append(config)
            projects[team] = team_projects
    state.init_projects(projects)
    return state


def run(dry_run=False):
    settings = queries.get_app_interface_settings()
    gqlapi = gql.get_api()

    # Reconcile against all sentry instances
    result = gqlapi.query(SENTRY_INSTANCES_QUERY)
    for instance in result['instances']:
        token = secret_reader.read(
            instance['automationToken'], settings=settings)
        host = instance['consoleUrl']
        sentry_client = SentryClient(host, token)

        skip_user = secret_reader.read(
            instance['adminUser'], settings=settings)
        current_state = fetch_current_state(sentry_client, [skip_user])
        desired_state = fetch_desired_state(gqlapi, instance)

        reconciler = SentryReconciler(sentry_client, dry_run)
        reconciler.reconcile(current_state, desired_state)
