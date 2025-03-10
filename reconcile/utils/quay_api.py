import requests


class QuayTeamNotFoundException(Exception):
    pass


class QuayApi:
    LIMIT_FOLLOWS = 15

    def __init__(self, token, organization, base_url="quay.io", timeout=60):
        self.token = token
        self.organization = organization
        self.auth_header = {"Authorization": "Bearer %s" % (token,)}
        self.team_members = {}
        self.api_url = f"https://{base_url}/api/v1"

        self._timeout = timeout
        """Timeout to use for HTTP calls to Quay (seconds)."""

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

        url = f"{self.api_url}/organization/{self.organization}/team/{team}/members?includePending=true"

        r = requests.get(url, headers=self.auth_header, timeout=self._timeout)
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
        members = {member["name"] for member in body["members"]}

        members_list = list(members)
        self.team_members[team] = members_list

        return members_list

    def user_exists(self, user):
        url = f"{self.api_url}/users/{user}"
        r = requests.get(url, headers=self.auth_header, timeout=self._timeout)
        return r.ok

    def remove_user_from_team(self, user, team):
        """Deletes an user from a team.

        :raises HTTPError if there are any problems with the request
        """
        url_team = f"{self.api_url}/organization/{self.organization}/team/{team}/members/{user}"

        r = requests.delete(url_team, headers=self.auth_header, timeout=self._timeout)
        if not r.ok:
            message = r.json().get("message", "")

            expected_message = f"User {user} does not belong to team {team}"

            if message != expected_message:
                r.raise_for_status()

        url_org = f"{self.api_url}/organization/{self.organization}/members/{user}"

        r = requests.delete(url_org, headers=self.auth_header, timeout=self._timeout)
        r.raise_for_status()

        return True

    def add_user_to_team(self, user, team):
        """Adds an user to a team.

        :raises HTTPError if there are any errors with the request
        """
        if user in self.list_team_members(team, cache=True):
            return True

        url = f"{self.api_url}/organization/{self.organization}/team/{team}/members/{user}"
        r = requests.put(url, headers=self.auth_header, timeout=self._timeout)
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

        url = f"{self.api_url}/organization/{self.organization}/team/{team}"

        payload = {"role": role}

        if description:
            payload.update({"description": description})

        r = requests.put(
            url, headers=self.auth_header, json=payload, timeout=self._timeout
        )
        r.raise_for_status()

    def list_images(self, images=None, page=None, count=0):
        """
        https://docs.quay.io/api/swagger/#!/repository/listRepos

        :raises HTTPError: failure when listing the images in the repository
        :raises ValueError: Following limit exceeded
        """

        if count > self.LIMIT_FOLLOWS:
            raise ValueError("Too many page follows")

        url = f"{self.api_url}/repository"

        # params
        params = {"namespace": self.organization}
        if page:
            params["next_page"] = page

        # perform request
        r = requests.get(
            url, params=params, headers=self.auth_header, timeout=self._timeout
        )
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
        return images

    def repo_create(self, repo_name, description, public):
        """Creates a repository called repo_name with the given description
        and public flag.

        :raise HTTPError: the operation fails
        """
        visibility = "public" if public else "private"

        url = f"{self.api_url}/repository"

        params = {
            "repo_kind": "image",
            "namespace": self.organization,
            "visibility": visibility,
            "repository": repo_name,
            "description": description,
        }

        # perform request
        r = requests.post(
            url, json=params, headers=self.auth_header, timeout=self._timeout
        )
        r.raise_for_status()

    def repo_delete(self, repo_name):
        url = f"{self.api_url}/repository/{self.organization}/{repo_name}"

        # perform request
        r = requests.delete(url, headers=self.auth_header, timeout=self._timeout)
        r.raise_for_status()

    def repo_update_description(self, repo_name, description):
        url = f"{self.api_url}/repository/{self.organization}/{repo_name}"

        params = {"description": description}

        # perform request
        r = requests.put(
            url, json=params, headers=self.auth_header, timeout=self._timeout
        )
        r.raise_for_status()

    def repo_make_public(self, repo_name):
        self._repo_change_visibility(repo_name, "public")

    def repo_make_private(self, repo_name):
        self._repo_change_visibility(repo_name, "private")

    def _repo_change_visibility(self, repo_name, visibility):
        url = f"{self.api_url}/repository/{self.organization}/{repo_name}/changevisibility"

        params = {"visibility": visibility}

        # perform request
        r = requests.post(
            url, json=params, headers=self.auth_header, timeout=self._timeout
        )
        r.raise_for_status()

    def get_repo_team_permissions(self, repo_name, team):
        url = (
            f"{self.api_url}/repository/{self.organization}/"
            + f"{repo_name}/permissions/team/{team}"
        )
        r = requests.get(url, headers=self.auth_header, timeout=self._timeout)
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
        r = requests.put(
            url, json=body, headers=self.auth_header, timeout=self._timeout
        )
        r.raise_for_status()
