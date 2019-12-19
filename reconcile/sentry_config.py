import logging
import reconcile.queries as queries
import utils.gql as gql
import utils.secret_reader as secret_reader

from reconcile.github_users import init_github
from utils.config import get_config
from utils.sentry_client import SentryClient


SENTRY_PROJECTS_QUERY = """
{
  apps: apps_v1 {
    sentryProjects {
      team {
        name
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
    permissions {
      service
      ...on PermissionSentryTeam_v1 {
        team
      }
    }
  }
}
"""

SENTRY_TEAMS_QUERY = """
{
  teams: sentry_teams_v1 {
    name
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
  
  def init_users_from_current_state(self, users):
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
          "name": p["name"],
          "email_prefix": p["subjectPrefix"],
          "platform": p["platform"]
        }
        if "sensitiveFields" in p.keys():
          pdata["sensitive_fields"] = p["sensitiveFields"]
        if "safeFields" in p.keys():
          pdata["safe_fields"] = p["safeFields"]
        if "resolveAge" in p.keys():
          pdata["auto_resolve_age"] = p["resolveAge"]
        if "allowedDomains" in p.keys():
          pdata["allowed_domains"] = p["allowedDomains"]
        if team not in self.projects.keys():
          self.projects[team] = [pdata]
        else:
          self.projects[team].append(pdata)

  def init_projects_from_desired_state(self, projects):
    self.projects = projects

  def init_teams(self, teams):
    self.teams = teams

class SentryReconciler:
  def __init__(self, client, dry_run):
    self.client = client
    self.dry_run = dry_run

  def reconcile(self, current, desired):
    # Reconcile the teams frist
    for team in current.teams:
      if team not in desired.teams:
        logging.info("deleting sentry team %s" % team)
        if not self.dry_run:
          self.client.delete_team(team)

    for team in desired.teams:
      if team not in current.teams:
        logging.info("creating sentry team %s" % team)
        if not self.dry_run:
          self.client.create_team(team)

    # Reconcile users
    for user in current.users.keys():
      if user not in desired.users.keys():
        logging.info("deleting sentry user %s" % user)
        if not self.dry_run:
          self.client.delete_user(user)

    for user in desired.users.keys():
      teams = desired.users[user]
      if user not in current.users.keys():
        logging.info("adding sentry user %s with teams %s" % (user, ",".join(teams)))
        if not self.dry_run:
          self.client.create_user(user, "member", teams)
      else:
        logging.info("setting sentry user %s team membership to %s" % (user, ",".join(teams)))
        if not self.dry_run:
          self.client.set_user_teams(user, teams)
        logging.info("setting user role for %s to %s" % (user, "member"))
        if not self.dry_run:
          self.client.change_user_role(user, "member")

    # Reconcile projects
    for projects in current.projects.values():
      for current_project in projects:
        if project_in_project_list(current_project, desired.projects.values()):
          continue
        project_name = current_project["name"]
        logging.info("deleting project %s" % project_name)
        if not self.dry_run:
          self.client.delete_project(project_name)

    for team in desired.projects.keys():
      for desired_project in desired.projects[team]:
        project_name = desired_project["name"]
        if not project_in_project_list(desired_project, current.projects.values()):
          logging.info("adding project %s" % project_name)
          if not self.dry_run:
            self.client.create_project(team, project_name)
        str = ("setting project config to {}").format(desired_project)
        logging.info(str)
        if not self.dry_run:
          self.client.update_project(project_name, desired_project)


def project_in_project_list(project, list):
  for projects in list:
    for p in projects:
      if p["name"] == project["name"]:
        return True
  return False

def fetch_current_state(client, ignore_users):
  state = SentryState()

  # Retrieve all the teams
  sentry_teams = client.get_teams()
  teams = []
  for team in sentry_teams:
    teams.append(team["slug"])
  state.init_teams(teams)

  # Retrieve the projects and the teams associated with them
  sentry_projects = client.get_projects()
  projects = {}
  for sentry_project in sentry_projects:
    project_slug = sentry_project["slug"]
    if project_slug == "internal":
      # This project can't be deleted
      continue
    project = client.get_project(project_slug)
    project_teams = []
    for team in project["teams"]:
      project_teams.append(team["slug"])
    projects[project_slug] = project_teams
  state.init_projects_from_current_state(client, projects)
    
  # Retrieve the users and the teams they are part of
  sentry_users = client.get_users()
  users = {}
  for sentry_user in sentry_users:
    user_name = sentry_user["email"]
    if user_name in ignore_users:
      continue
    user = client.get_user(user_name)
    teams = []
    for team in user["teams"]:
      teams.append(team)
    users[user_name] = teams
  state.init_users_from_current_state(users)
  return state

def fetch_desired_state():
  state = SentryState()
  gqlapi = gql.get_api()

  # Query for users that should be in sentry
  team_members = {}
  result = gqlapi.query(SENTRY_USERS_QUERY)
  github = init_github()
  for role in result['roles']:
    permissions = list(filter(
      lambda p: p.get('service') == 'sentry-membership',
      role['permissions']
    ))

    for permission in permissions:
      # Users that should exist
      members = []
      team = permission["team"]

      def append_github_username_members(member):
        github_username = member.get('github_username')
        if github_username:
          user_info = github.get_user(login=github_username)
          email = user_info.email
          if email != None:
            members.append(email)

      for user in role['users']:
        append_github_username_members(user)

      for bot in role['bots']:
        append_github_username_members(bot)
      if team not in team_members.keys():
        team_members[team] = members
      else:
        team_members[team].extend(members)
  state.init_users_from_desired_state(team_members)

  # Query for teams that should be in sentry
  result = gqlapi.query(SENTRY_TEAMS_QUERY)
  teams = []
  for team in result['teams']:
    if team in teams:
      logging.error("sentry team %s already exists" % team)
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
      team = sentry_project["team"]["name"]
      team_projects = []
      for project_config in sentry_project["projects"]:
        if project_in_project_list(project_config, projects.values()):
          logging.error("sentry project %s already exists" % project_config["name"])
          continue
          
        config = {}
        for field in project_config.keys():
          if project_config[field] != None:
            config[field] = project_config[field]
        team_projects.append(config)
      projects[team] = team_projects
  state.init_projects_from_desired_state(projects)
  return state

def run(dry_run=False):
  settings = queries.get_app_interface_settings()
  secret = {
    "path": path,
    "field": field,
  }
  host = secret_reader.read(secret, settings)
  secret["field"] = field
  token = secret_reader.read(secret, settings)

  secret["path"] = path
  secret["field"] = field
  skip_users = secret_reader.read(secret, settings)

  sentry_client = SentryClient(host, token)
  current_state = fetch_current_state(sentry_client, [skip_users])
  desired_state = fetch_desired_state()

  reconciler = SentryReconciler(sentry_client, dry_run)
  reconciler.reconcile(current_state, desired_state)