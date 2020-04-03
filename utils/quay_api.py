import requests


class RequestsException(Exception):
    def __init__(self, r):
        message = "\nCode: %s\n%s" % (r.status_code, r.text)
        super(Exception, self).__init__(message)


class QuayApi(object):
    API_URL = 'https://quay.io/api/v1'
    LIMIT_FOLLOWS = 15

    def __init__(self, token, organization, team=None):
        self.token = token
        self.organization = organization
        self.team = team
        self.auth_header = {"Authorization": "Bearer %s" % (token,)}
        self.team_members = None

    def list_team_members(self, **kwargs):
        if self.team is None:
            raise('Must define "team"')

        if kwargs.get("cache") and self.team_members:
            return self.team_members

        url = "{}/organization/{}/team/{}/members?includePending=true".format(
            self.API_URL, self.organization, self.team)

        r = requests.get(url, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)

        body = r.json()

        # Using a set because members may be repeated
        members = set()
        for member in body[u'members']:
            members.add(member[u'name'])

        self.team_members = list(members)

        return self.team_members

    def user_exists(self, user):
        url = "{}/users/{}".format(self.API_URL, user)
        r = requests.get(url, headers=self.auth_header)
        if not r.ok:
            return False
        return True

    def remove_user(self, user):
        if self.team is None:
            raise('Must define "team"')

        url_team = "{}/organization/{}/team/{}/members/{}".format(
            self.API_URL, self.organization,
            self.team, user
        )

        r = requests.delete(url_team, headers=self.auth_header)
        if not r.ok:
            message = r.json()['message']

            expected_message = "User {} does not belong to team {}".format(
                user, self.team)

            if message != expected_message:
                raise RequestsException(r)

        url_org = "{}/organization/{}/members/{}".format(
            self.API_URL, self.organization, user)

        r = requests.delete(url_org, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)

        return True

    def add_user_team(self, user):
        if self.team is None:
            raise('Must define "team"')

        if user in self.list_team_members(cache=True):
            return True

        url = "{}/organization/{}/team/{}/members/{}".format(
            self.API_URL, self.organization, self.team, user)
        r = requests.put(url, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)
        return True

    def list_images(self, images=None, page=None, count=0):
        """
        https://docs.quay.io/api/swagger/#!/repository/listRepos
        """

        if count > self.LIMIT_FOLLOWS:
            raise("Too many page follows")

        url = "{}/repository".format(self.API_URL)

        # params
        params = {'namespace': self.organization}
        if page:
            params['next_page'] = page

        # perform request
        r = requests.get(url, params=params, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)

        # read body
        body = r.json()
        repositories = body.get('repositories', [])
        next_page = body.get('next_page')

        # append images
        if images is None:
            images = []

        images += repositories

        if next_page:
            return self.list_images(images, next_page, count+1)
        else:
            return images

    def repo_create(self, repo_name, description, public):
        visibility = "public" if public else "private"

        url = "{}/repository".format(self.API_URL)

        params = {
            "repo_kind": "image",
            "namespace": self.organization,
            "visibility": visibility,
            "repository": repo_name,
            "description": description
        }

        # perform request
        r = requests.post(url, json=params, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)

    def repo_delete(self, repo_name):
        url = "{}/repository/{}/{}".format(
            self.API_URL, self.organization, repo_name
        )

        # perform request
        r = requests.delete(url, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)

    def repo_update_description(self, repo_name, description):
        url = "{}/repository/{}/{}".format(
            self.API_URL,
            self.organization,
            repo_name
        )

        params = {
            "description": description
        }

        # perform request
        r = requests.put(url, json=params, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)

    def repo_make_public(self, repo_name):
        self._repo_change_visibility(repo_name, "public")

    def repo_make_private(self, repo_name):
        self._repo_change_visibility(repo_name, "private")

    def _repo_change_visibility(self, repo_name, visibility):
        url = "{}/repository/{}/{}/changevisibility".format(
            self.API_URL, self.organization, repo_name
        )

        params = {
            "visibility": visibility
        }

        # perform request
        r = requests.post(url, json=params, headers=self.auth_header)
        if not r.ok:
            raise RequestsException(r)
