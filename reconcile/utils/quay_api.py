import requests


class QuayTeamNotFoundException(Exception):
    pass


class QuayApi:
    LIMIT_FOLLOWS = 15

    def __init__(self, token, organization, base_url="quay.io"):
        self.token = token
        self.organization = organization
        self.auth_header = {"Authorization": "Bearer %s" % (token,)}
        self.team_members = {}
        self.api_url = f"https://{base_url}/api/v1"

    def list_team_members(self, team, **kwargs):
        """
        List Quay team members.

        :raises QuayTeamNotFoundException: if Quay team doesn't exist (404)
        :raises HTTPError: any HTTP status codes >= 400, but not 404
        """
        if kwargs.get("cache"):
            cache_members = self.team_members.get(team)
            if cache_members:
                return cache_members

        url = "{}/organization/{}/team/{}/members?includePending=true".format(
            self.api_url, self.organization, team
        )

        r = requests.get(url, headers=self.auth_header)
        if r.status_code == 404:
            raise QuayTeamNotFoundException(
                f"team {team} is not found in "
                f"org {self.organization}. "
                f"contact org owner to create the "
                f"team manually."
            )
        r.raise_for_status()

        body = r.json()

        # Using a set because members may be repeated
        members = set()
        for member in body["members"]:
            members.add(member["name"])

        members_list = list(members)
        self.team_members[team] = members_list

        return members_list

    def user_exists(self, user):
        url = "{}/users/{}".format(self.api_url, user)
        r = requests.get(url, headers=self.auth_header)
        if not r.ok:
            return False
        return True

    def remove_user_from_team(self, user, team):
        """Deletes an user from a team.

        :raises HTTPError if there are any problems with the request
        """
        url_team = "{}/organization/{}/team/{}/members/{}".format(
            self.api_url, self.organization, team, user
        )

        r = requests.delete(url_team, headers=self.auth_header)
        if not r.ok:
            message = r.json().get("message", "")

            expected_message = "User {} does not belong to team {}".format(user, team)

            if message != expected_message:
                r.raise_for_status()

        url_org = "{}/organization/{}/members/{}".format(
            self.api_url, self.organization, user
        )

        r = requests.delete(url_org, headers=self.auth_header)
        r.raise_for_status()

        return True

    def add_user_to_team(self, user, team):
        """Adds an user to a team.

        :raises HTTPError if there are any errors with the request
        """
        if user in self.list_team_members(team, cache=True):
            return True

        url = "{}/organization/{}/team/{}/members/{}".format(
            self.api_url, self.organization, team, user
        )
        r = requests.put(url, headers=self.auth_header)
        r.raise_for_status()
        return True

    def create_or_update_team(self, team: str, role="member", description=None) -> None:
        """
        Create or update an Organization team.

        https://docs.quay.io/api/swagger/#!/team/updateOrganizationTeam

        :param team: The name of the team
        :param role: The default role to associate with the team
        :param description: Team description
        :raises HTTPError: unsuccessful attempt to create the team
        """

        url = "{}/organization/{}/team/{}".format(self.api_url, self.organization, team)

        payload = {"role": role}

        if description:
            payload.update({"description": description})

        r = requests.put(url, headers=self.auth_header, json=payload)
        r.raise_for_status()

    def list_images(self, images=None, page=None, count=0):
        """
        https://docs.quay.io/api/swagger/#!/repository/listRepos

        :raises HTTPError: failure when listing the images in the repository
        :raises ValueError: Following limit exceeded
        """

        if count > self.LIMIT_FOLLOWS:
            raise ValueError("Too many page follows")

        url = "{}/repository".format(self.api_url)

        # params
        params = {"namespace": self.organization}
        if page:
            params["next_page"] = page

        # perform request
        r = requests.get(url, params=params, headers=self.auth_header)
        r.raise_for_status()

        # read body
        body = r.json()
        repositories = body.get("repositories", [])
        next_page = body.get("next_page")

        # append images
        if images is None:
            images = []

        images += repositories

        if next_page:
            return self.list_images(images, next_page, count + 1)
        else:
            return images

    def repo_create(self, repo_name, description, public):
        """Creates a repository called repo_name with the given description
        and public flag.

        :raise HTTPError: the operation fails
        """
        visibility = "public" if public else "private"

        url = "{}/repository".format(self.api_url)

        params = {
            "repo_kind": "image",
            "namespace": self.organization,
            "visibility": visibility,
            "repository": repo_name,
            "description": description,
        }

        # perform request
        r = requests.post(url, json=params, headers=self.auth_header)
        r.raise_for_status()

    def repo_delete(self, repo_name):
        url = "{}/repository/{}/{}".format(self.api_url, self.organization, repo_name)

        # perform request
        r = requests.delete(url, headers=self.auth_header)
        r.raise_for_status()

    def repo_update_description(self, repo_name, description):
        url = "{}/repository/{}/{}".format(self.api_url, self.organization, repo_name)

        params = {"description": description}

        # perform request
        r = requests.put(url, json=params, headers=self.auth_header)
        r.raise_for_status()

    def repo_make_public(self, repo_name):
        self._repo_change_visibility(repo_name, "public")

    def repo_make_private(self, repo_name):
        self._repo_change_visibility(repo_name, "private")

    def _repo_change_visibility(self, repo_name, visibility):
        url = "{}/repository/{}/{}/changevisibility".format(
            self.api_url, self.organization, repo_name
        )

        params = {"visibility": visibility}

        # perform request
        r = requests.post(url, json=params, headers=self.auth_header)
        r.raise_for_status()

    def get_repo_team_permissions(self, repo_name, team):
        url = (
            f"{self.api_url}/repository/{self.organization}/"
            + f"{repo_name}/permissions/team/{team}"
        )
        r = requests.get(url, headers=self.auth_header)
        if not r.ok:
            message = r.json().get("message")
            expected_message = "Team does not have permission for repo."
            if message == expected_message:
                return None

            r.raise_for_status()

        return r.json().get("role") or None

    def set_repo_team_permissions(self, repo_name, team, role):
        url = (
            f"{self.api_url}/repository/{self.organization}/"
            + f"{repo_name}/permissions/team/{team}"
        )
        body = {"role": role}
        r = requests.put(url, json=body, headers=self.auth_header)
        r.raise_for_status()
