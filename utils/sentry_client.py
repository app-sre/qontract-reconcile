import requests
import json

class SentryClient:
  ORGANIZATION = "sentry"

  def __init__(self, host, token):
    self.host = host
    self.auth_token = token

  def do_sentry_api_call(self, method, path, slugs, payload=None):
    success_codes = {"get": 200, "post": 201, "delete": 204, "put": 200}
    url = "%s/api/0/%s/" % (self.host, path)

    if len(slugs) > 0:
      url = "%s%s/" % (url, "/".join(slugs))

    headers = {"Authorization": "Bearer " + self.auth_token}
    call = getattr(requests, method, None)
    if call == None:
      print ("invalid http method %s" % method)
      return None

    response = call(url, headers=headers, json=payload)
    if response.status_code != success_codes[method]:
      print ("error: http %s returned %d trying to access %s" % (method, response.status_code, url))
      return None

    if response.status_code != 204:
      return response.json()


  # Organization functions
  def get_organizations(self):
    request = self.do_sentry_api_call("get", "organizations", [])
    return request

  def get_organization(self, slug):
    request = self.do_sentry_api_call("get", "organizations", [slug])
    return request


  # Project functions
  def get_projects(self):
    request = self.do_sentry_api_call("get", "projects", [])
    return request

  def get_project(self, slug):
    request = self.do_sentry_api_call("get", "projects", [self.ORGANIZATION, slug])
    return request

  def create_project(self, team_slug, name, slug=None):
    params = {"name": name}
    if slug != None:
      params["slug"] = slug
    request = self.do_sentry_api_call("post", "teams", [self.ORGANIZATION, team_slug, "projects"], payload=params)
    return request

  def delete_project(self, slug):
    request = self.do_sentry_api_call("delete", "projects", [self.ORGANIZATION, slug])
    return request

  def get_project_key(self, slug):
    request = self.do_sentry_api_call("get", "projects", [self.ORGANIZATION, slug, "keys"])
    keys = {"dsn": request[0]["dsn"]["public"], "deprecated": request[0]["dsn"]["secret"]}
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

    request = self.do_sentry_api_call("put", "projects", [self.ORGANIZATION, slug], payload=params)
    return request

  # Team functions
  def get_teams(self):
    request = self.do_sentry_api_call("get", "organizations", [self.ORGANIZATION, "teams"])
    return request

  def get_team_members(self, team_slug):
    request = self.do_sentry_api_call("get", "teams", [self.ORGANIZATION, team_slug, "members"])
    return request

  def create_team(self, slug):
    params = {"slug": slug}
    request = self.do_sentry_api_call("post", "organizations", [self.ORGANIZATION, "teams"], payload=params)
    return request

  def delete_team(self, slug):
    request = self.do_sentry_api_call("delete", "teams", [self.ORGANIZATION, slug])
    return request

  def get_team_projects(self, slug):
    request = self.do_sentry_api_call("get", "teams", [self.ORGANIZATION, slug, "projects"])
    return request

    
  # User/Member functions
  def get_users(self):
    request = self.do_sentry_api_call("get", "organizations", [self.ORGANIZATION, "members"])
    return request

  def get_user(self, email):
    users = self.get_users()
    for u in users:
      if u["email"] == email:
        user = u
        break
    request = self.do_sentry_api_call("get", "organizations", [self.ORGANIZATION, "members", user["id"]])
    return request

  def create_user(self, email, role, teams=[]):
    params = {"email": email, "role": role, "teams": teams}
    request = self.do_sentry_api_call("post", "organizations", [self.ORGANIZATION, "members"], payload=params)
    return request

  def delete_user(self, email):
    user = self.get_user(email)
    request = self.do_sentry_api_call("delete", "organizations", [self.ORGANIZATION, "members", user["id"]])
    return request

  def set_user_teams(self, email, teams):
    user = self.get_user(email)
    params = {"teams": teams}
    request = self.do_sentry_api_call("put", "organizations", [self.ORGANIZATION, "members", user["id"]], payload=params)
    return request

  def remove_user_from_teams(self, email, teams):
    user = self.get_user(email)
    user_teams = user["teams"]
    for t in teams:
      if t in user_teams:
        user_teams.remove(t)
    params = {"teams": user_teams}
    request = self.do_sentry_api_call("put", "organizations", [self.ORGANIZATION, "members", user["id"]], payload=params)
    return request

  def change_user_role(self, email, role):
    user = self.get_user(email)
    params = {"role": role}
    request = self.do_sentry_api_call("put", "organizations", [self.ORGANIZATION, "members", user["id"]], payload=params)
    return request