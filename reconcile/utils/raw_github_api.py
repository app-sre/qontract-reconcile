import os

import requests
from sretoolbox.utils import retry


class RawGithubApi:
    """
    REST based GH interface

    Unfortunately this needs to be used because PyGithub does not yet support
    checking pending invitations
    """

    BASE_URL = os.environ.get("GITHUB_API", "https://api.github.com")
    BASE_HEADERS = {
        "Accept": "application/vnd.github.v3+json,"
        "application/vnd.github.dazzler-preview+json"
    }

    def __init__(self, password):
        self.password = password

    def headers(self, headers=None):
        if headers is None:
            headers = {}
        new_headers = headers.copy()
        new_headers.update(self.BASE_HEADERS)
        new_headers["Authorization"] = "token %s" % (self.password,)
        return new_headers

    def patch(self, url):
        res = requests.patch(url, headers=self.headers(), timeout=60)
        res.raise_for_status()
        return res

    @retry()
    def query(self, url, headers=None):
        if headers is None:
            headers = {}
        h = self.headers(headers)
        res = requests.get(self.BASE_URL + url, headers=h, timeout=60)
        res.raise_for_status()
        result = res.json()

        if isinstance(result, list):
            elements = []

            for element in result:
                elements.append(element)

            while "last" in res.links and "next" in res.links:
                if res.links["last"]["url"] == res.links["next"]["url"]:
                    req_url = res.links["next"]["url"]
                    res = requests.get(req_url, headers=h, timeout=60)
                    res.raise_for_status()

                    for element in res.json():
                        elements.append(element)

                    return elements

                req_url = res.links["next"]["url"]
                res = requests.get(req_url, headers=h, timeout=60)
                res.raise_for_status()

                for element in res.json():
                    elements.append(element)

            return elements

        return result

    def org_invitations(self, org):
        invitations = self.query("/orgs/{}/invitations".format(org))

        return [
            login
            for login in (invitation.get("login") for invitation in invitations)
            if login is not None
        ]

    def team_invitations(self, org_id, team_id):
        invitations = self.query(
            "/organizations/{}/team/{}/invitations".format(org_id, team_id)
        )

        return [
            login
            for login in (invitation.get("login") for invitation in invitations)
            if login is not None
        ]

    def repo_invitations(self):
        return self.query("/user/repository_invitations")

    def accept_repo_invitation(self, invitation_id):
        url = self.BASE_URL + "/user/repository_invitations/{}".format(invitation_id)
        res = self.patch(url)
        res.raise_for_status()
