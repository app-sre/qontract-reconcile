import functools
import json
import parse
import requests

from sretoolbox.utils import retry


class SentryClient:  # pylint: disable=too-many-public-methods
    ORGANIZATION = "sentry"

    def __init__(self, host, token):
        self.host = host
        self.auth_token = token

    @retry()
    def _do_sentry_api_call(self, method, path, slugs, payload=None):
        url = f"{self.host}/api/0/{path}/"

        if len(slugs) > 0:
            url = f"{url}{'/'.join(slugs)}/"

        headers = {"Authorization": "Bearer " + self.auth_token}
        call = getattr(requests, method, None)
        if call is None:
            raise ValueError(f"invalid http method {method}")

        response = call(url, headers=headers, json=payload)
        response.raise_for_status()

        try:
            all_results = response.json()
        except json.decoder.JSONDecodeError:
            return

        # there may be more pages if the response contains a link header
        # link is a string of comma separated items
        # with the following structure:
        # <URL>; rel="previous/next"; results="false/true"; cursor="value"
        item_format = '<{}>; rel="{}"; results="{}"; cursor="{}"'
        while True:
            link = response.headers.get("link")
            if not link:
                break
            # 2nd item is the next page
            next_item = link.split(", ")[1]
            # copied with love from
            # https://stackoverflow.com/questions/10663093/
            # use-python-format-string-in-reverse-for-parsing
            _, rel, results, cursor = parse.parse(item_format, next_item)
            if rel != "next" or results != "true":
                break
            response = call(f"{url}?&cursor={cursor}", headers=headers, json=payload)
            response.raise_for_status()
            # if there are pages, each response is a list to extend
            all_results += response.json()

        return all_results

    # Organization functions
    @functools.lru_cache(maxsize=128)
    def get_organizations(self):
        response = self._do_sentry_api_call("get", "organizations", [])
        return response

    def get_organization(self, slug):
        response = self._do_sentry_api_call("get", "organizations", [slug])
        return response

    # Project functions
    @functools.lru_cache(maxsize=128)
    def get_projects(self):
        response = self._do_sentry_api_call("get", "projects", [])
        return response

    def get_project(self, slug):
        response = self._do_sentry_api_call(
            "get", "projects", [self.ORGANIZATION, slug]
        )
        return response

    def create_project(self, team_slug, name, slug=None):
        params = {"name": name}
        if slug is not None:
            params["slug"] = slug
        response = self._do_sentry_api_call(
            "post", "teams", [self.ORGANIZATION, team_slug, "projects"], payload=params
        )
        return response

    def delete_project(self, slug):
        response = self._do_sentry_api_call(
            "delete", "projects", [self.ORGANIZATION, slug]
        )
        return response

    def get_project_key(self, slug):
        response = self._do_sentry_api_call(
            "get", "projects", [self.ORGANIZATION, slug, "keys"]
        )
        keys = {
            "dsn": response[0]["dsn"]["public"],
            "deprecated": response[0]["dsn"]["secret"],
        }
        return keys

    def update_project(self, slug, options):
        params = {}
        required_fields = self.required_project_fields()
        for k, v in required_fields.items():
            if v in options:
                params[k] = options[v]

        self.validate_project_options(options)
        optional_fields = self.optional_project_fields()
        for k, v in optional_fields.items():
            if v in options:
                params[k] = options[v]

        response = self._do_sentry_api_call(
            "put", "projects", [self.ORGANIZATION, slug], payload=params
        )
        return response

    @staticmethod
    def required_project_fields():
        required_fields = {"platform": "platform", "subjectPrefix": "email_prefix"}
        return required_fields

    @staticmethod
    def optional_project_fields():
        optional_fields = {
            "sensitiveFields": "sensitive_fields",
            "safeFields": "safe_fields",
            "resolveAge": "auto_resolve_age",
            "allowedDomains": "allowed_domains",
        }
        return optional_fields

    def validate_project_options(self, options):
        # If the resolve age is not one of these then sentry will set to 0.
        # These are the values selectable in the sentry UI in number of hours
        valid_resolve_age = [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            15,
            18,
            21,
            24,
            30,
            36,
            48,
            72,
            96,
            120,
            144,
            168,
            192,
            216,
            240,
            288,
            312,
            336,
            360,
            384,
            408,
            432,
            456,
            480,
            504,
            528,
            552,
            576,
            600,
            624,
            648,
            672,
            696,
            720,
        ]

        optional_fields = self.optional_project_fields()
        resolve_age_field = optional_fields["resolveAge"]
        if (
            resolve_age_field in options
            and options[resolve_age_field] not in valid_resolve_age
        ):
            # If an option is set and invalid, raise exception rather than
            # potentially destroying setting by trying to set invalid value
            raise ValueError(
                f"invalid {resolve_age_field} {options[resolve_age_field]}"
            )

    def get_project_alert_rules(self, slug):
        response = self._do_sentry_api_call(
            "get", "projects", [self.ORGANIZATION, slug, "rules"]
        )
        return response

    def delete_project_alert_rule(self, slug, rule):
        response = self._do_sentry_api_call(
            "delete", "projects", [self.ORGANIZATION, slug, "rules", rule["id"]]
        )
        return response

    def get_project_owners(self, slug):
        teams = self._do_sentry_api_call(
            "get", "projects", [self.ORGANIZATION, slug, "teams"]
        )
        return teams

    def add_project_owner(self, project_slug, team_slug):
        response = self._update_project_owner_("post", project_slug, team_slug)
        return response

    def delete_project_owner(self, project_slug, team_slug):
        response = self._update_project_owner_("delete", project_slug, team_slug)
        return response

    def _update_project_owner_(self, method, pslug, tslug):
        params = {
            "organization_slug": self.ORGANIZATION,
            "project_slug": pslug,
            "team_slug": tslug,
        }

        response = self._do_sentry_api_call(
            method,
            "projects",
            [self.ORGANIZATION, pslug, "teams", tslug],
            payload=params,
        )
        return response

    # Team functions
    def get_teams(self):
        response = self._do_sentry_api_call(
            "get", "organizations", [self.ORGANIZATION, "teams"]
        )
        return response

    def get_team_members(self, team_slug):
        response = self._do_sentry_api_call(
            "get", "teams", [self.ORGANIZATION, team_slug, "members"]
        )
        return response

    def create_team(self, slug):
        params = {"slug": slug}
        response = self._do_sentry_api_call(
            "post", "organizations", [self.ORGANIZATION, "teams"], payload=params
        )
        return response

    def delete_team(self, slug):
        response = self._do_sentry_api_call(
            "delete", "teams", [self.ORGANIZATION, slug]
        )
        return response

    def get_team_projects(self, slug):
        response = self._do_sentry_api_call(
            "get", "teams", [self.ORGANIZATION, slug, "projects"]
        )
        return response

    # User/Member functions
    @functools.lru_cache(maxsize=128)
    def get_users(self):
        response = self._do_sentry_api_call(
            "get", "organizations", [self.ORGANIZATION, "members"]
        )
        return response

    def get_user(self, email):
        users = self.get_users()
        user_list = []
        for u in users:
            if u["email"] == email:
                user_list.append(u)

        response = []
        for user in user_list:
            resp = self._do_sentry_api_call(
                "get", "organizations", [self.ORGANIZATION, "members", user["id"]]
            )
            if resp is not None:
                response.append(resp)
        return response

    def create_user(self, email, role, teams=None):
        if teams is None:
            teams = []
        params = {"email": email, "role": role, "teams": teams}
        response = self._do_sentry_api_call(
            "post", "organizations", [self.ORGANIZATION, "members"], payload=params
        )
        return response

    def delete_user(self, email):
        user_list = self.get_user(email)
        resp = []
        for user in user_list:
            response = self._do_sentry_api_call(
                "delete", "organizations", [self.ORGANIZATION, "members", user["id"]]
            )
            if response is not None and len(response) > 0:
                resp.append(response)
        return resp

    def delete_user_by_id(self, id):
        response = self._do_sentry_api_call(
            "delete", "organizations", [self.ORGANIZATION, "members", id]
        )
        return response

    def set_user_teams(self, email, teams):
        user_list = self.get_user(email)
        if len(user_list) > 1:
            raise ValueError(
                "set_user_teams will only work for 1 user per "
                f"e-mail. E-mail {email} has {len(user_list)} "
                "accounts"
            )
        user = user_list[0]
        params = {"teams": teams}
        response = self._do_sentry_api_call(
            "put",
            "organizations",
            [self.ORGANIZATION, "members", user["id"]],
            payload=params,
        )
        return response

    def remove_user_from_teams(self, email, teams):
        user_list = self.get_user(email)
        if len(user_list) > 1:
            raise ValueError(
                "remove_user_from_teams will only work for 1 "
                f"user per e-mail. E-mail {email} has "
                f"{len(user_list)} accounts"
            )
        user = user_list[0]
        user_teams = user["teams"]
        for t in teams:
            if t in user_teams:
                user_teams.remove(t)
        params = {"teams": user_teams}
        response = self._do_sentry_api_call(
            "put",
            "organizations",
            [self.ORGANIZATION, "members", user["id"]],
            payload=params,
        )
        return response

    def change_user_role(self, email, role):
        user_list = self.get_user(email)
        if len(user_list) > 1:
            raise ValueError(
                "change_user_role will only work for 1 user per "
                f"e-mail. E-mail {email} has {len(user_list)} "
                "accounts"
            )
        user = user_list[0]
        params = {"role": role}
        response = self._do_sentry_api_call(
            "put",
            "organizations",
            [self.ORGANIZATION, "members", user["id"]],
            payload=params,
        )
        return response
