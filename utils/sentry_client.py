import requests
import json

class SentryClient:
  ORGANIZATION = "sentry"

  def __init__(self, host, token):
    self.host = host
    self.auth_token = token

  def _do_sentry_api_call_(self, method, path, slugs, payload=None):
    url = f"{self.host}/api/0/{path}/"

    if len(slugs) > 0:
      url = f"{url}{'/'.join(slugs)}/"

    headers = {"Authorization": "Bearer " + self.auth_token}
    call = getattr(requests, method, None)
    if call == None:
      raise Exception(f"invalid http method {method}")

    response = call(url, headers=headers, json=payload)
    response.raise_for_status()

    if response.status_code != 204:
      return response.json()


  # Organization functions
  def get_organizations(self):
    response = self._do_sentry_api_call_("get", "organizations", [])
    return response

  def get_organization(self, slug):
    response = self._do_sentry_api_call_("get", "organizations", [slug])
    return response


  # Project functions
  def get_projects(self):
    response = self._do_sentry_api_call_("get", "projects", [])
    return response

  def get_project(self, slug):
    response = self._do_sentry_api_call_("get", "projects", [self.ORGANIZATION, slug])
    return response

  def create_project(self, team_slug, name, slug=None):
    params = {"name": name}
    if slug != None:
      params["slug"] = slug
    response = self._do_sentry_api_call_("post", "teams", [self.ORGANIZATION, team_slug, "projects"], payload=params)
    return response

  def delete_project(self, slug):
    response = self._do_sentry_api_call_("delete", "projects", [self.ORGANIZATION, slug])
    return response

  def get_project_key(self, slug):
    response = self._do_sentry_api_call_("get", "projects", [self.ORGANIZATION, slug, "keys"])
    keys = {"dsn": response[0]["dsn"]["public"], "deprecated": response[0]["dsn"]["secret"]}
    return keys

  def update_project(self, slug, options):
    params = {
      "platform": options["platform"],
      "subjectPrefix": options["email_prefix"]
    }
    if "sensitive_fields" in options.keys():
      params["sensitiveFields"] = options["sensitive_Fields"]

    if "safe_fields" in options.keys():
      params["safeFields"] = options["safe_fields"]

    if "auto_resolve_age" in options.keys():
      params["resolveAge"] = options["auto_resolve_age"]

    if "allowed_domains" in options.keys():
      params["allowedDomains"] = options["allowed_domains"]

    response = self._do_sentry_api_call_("put", "projects", [self.ORGANIZATION, slug], payload=params)
    return response

  # Team functions
  def get_teams(self):
    response = self._do_sentry_api_call_("get", "organizations", [self.ORGANIZATION, "teams"])
    return response

  def get_team_members(self, team_slug):
    response = self._do_sentry_api_call_("get", "teams", [self.ORGANIZATION, team_slug, "members"])
    return response

  def create_team(self, slug):
    params = {"slug": slug}
    response = self._do_sentry_api_call_("post", "organizations", [self.ORGANIZATION, "teams"], payload=params)
    return response

  def delete_team(self, slug):
    response = self._do_sentry_api_call_("delete", "teams", [self.ORGANIZATION, slug])
    return response

  def get_team_projects(self, slug):
    response = self._do_sentry_api_call_("get", "teams", [self.ORGANIZATION, slug, "projects"])
    return response

    
  # User/Member functions
  def get_users(self):
    response = self._do_sentry_api_call_("get", "organizations", [self.ORGANIZATION, "members"])
    return response

  def get_user(self, email):
    users = self.get_users()
    for u in users:
      if u["email"] == email:
        user = u
        break
    response = self._do_sentry_api_call_("get", "organizations", [self.ORGANIZATION, "members", user["id"]])
    return response

  def create_user(self, email, role, teams=[]):
    params = {"email": email, "role": role, "teams": teams}
    response = self._do_sentry_api_call_("post", "organizations", [self.ORGANIZATION, "members"], payload=params)
    return response

  def delete_user(self, email):
    user = self.get_user(email)
    response = self._do_sentry_api_call_("delete", "organizations", [self.ORGANIZATION, "members", user["id"]])
    return response

  def set_user_teams(self, email, teams):
    user = self.get_user(email)
    params = {"teams": teams}
    response = self._do_sentry_api_call_("put", "organizations", [self.ORGANIZATION, "members", user["id"]], payload=params)
    return response

  def remove_user_from_teams(self, email, teams):
    user = self.get_user(email)
    user_teams = user["teams"]
    for t in teams:
      if t in user_teams:
        user_teams.remove(t)
    params = {"teams": user_teams}
    response = self._do_sentry_api_call_("put", "organizations", [self.ORGANIZATION, "members", user["id"]], payload=params)
    return response

  def change_user_role(self, email, role):
    user = self.get_user(email)
    params = {"role": role}
    response = self._do_sentry_api_call_("put", "organizations", [self.ORGANIZATION, "members", user["id"]], payload=params)
    return response