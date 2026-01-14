import contextlib
from typing import Any

import requests

from reconcile.utils.rest_api_base import ApiBase, BearerTokenAuth


class QuayTeamNotFoundError(Exception):
    pass


class QuayApi(ApiBase):
    LIMIT_FOLLOWS = 15

    def __init__(
        self,
        token: str,
        organization: str,
        base_url: str = "quay.io",
        timeout: int = 60,
    ) -> None:
        # Support both hostname (e.g., "quay.io") and full URLs (e.g., "http://localhost:12345")
        if base_url.startswith(("http://", "https://")):
            host = base_url
        else:
            host = f"https://{base_url}"
        super().__init__(
            host=host,
            auth=BearerTokenAuth(token),
            read_timeout=timeout,
        )
        self.organization = organization
        self.team_members: dict[str, Any] = {}

    def list_team_members(self, team: str, **kwargs: Any) -> list[dict]:
        """
        List Quay team members.

        :raises QuayTeamNotFoundException: if Quay team doesn't exist (404)
        :raises HTTPError: any HTTP status codes >= 400, but not 404
        """
        if kwargs.get("cache"):
            cache_members = self.team_members.get(team)
            if cache_members:
                return cache_members

        url = f"/api/v1/organization/{self.organization}/team/{team}/members"
        params = {"includePending": "true"}

        try:
            body = self._get(url, params=params)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise QuayTeamNotFoundError(
                    f"team {team} is not found in "
                    f"org {self.organization}. "
                    f"contact org owner to create the "
                    f"team manually."
                ) from e
            raise

        # Using a set because members may be repeated
        members = {member["name"] for member in body["members"]}

        members_list = list(members)
        self.team_members[team] = members_list

        return members_list

    def user_exists(self, user: str) -> bool:
        url = f"/api/v1/users/{user}"
        try:
            self._get(url)
            return True
        except requests.exceptions.HTTPError:
            return False

    def remove_user_from_team(self, user: str, team: str) -> bool:
        """Deletes an user from a team.

        :raises HTTPError if there are any problems with the request
        """
        url_team = (
            f"/api/v1/organization/{self.organization}/team/{team}/members/{user}"
        )

        try:
            self._delete(url_team)
        except requests.exceptions.HTTPError as e:
            message = ""
            if e.response is not None:
                with contextlib.suppress(ValueError, AttributeError):
                    message = e.response.json().get("message", "")

            expected_message = f"User {user} does not belong to team {team}"

            if message != expected_message:
                raise

        url_org = f"/api/v1/organization/{self.organization}/members/{user}"
        self._delete(url_org)

        return True

    def add_user_to_team(self, user: str, team: str) -> bool:
        """Adds an user to a team.

        :raises HTTPError if there are any errors with the request
        """
        if user in self.list_team_members(team, cache=True):
            return True

        url = f"/api/v1/organization/{self.organization}/team/{team}/members/{user}"
        self._put(url)
        return True

    def create_or_update_team(
        self, team: str, role: str = "member", description: str | None = None
    ) -> None:
        """
        Create or update an Organization team.

        https://docs.quay.io/api/swagger/#!/team/updateOrganizationTeam

        :param team: The name of the team
        :param role: The default role to associate with the team
        :param description: Team description
        :raises HTTPError: unsuccessful attempt to create the team
        """

        url = f"/api/v1/organization/{self.organization}/team/{team}"

        payload = {"role": role}

        if description:
            payload.update({"description": description})

        self._put(url, data=payload)

    def list_images(
        self, images: list | None = None, page: str | None = None, count: int = 0
    ) -> list[dict[str, Any]]:
        """
        https://docs.quay.io/api/swagger/#!/repository/listRepos

        :raises HTTPError: failure when listing the images in the repository
        :raises ValueError: Following limit exceeded
        """

        if count > self.LIMIT_FOLLOWS:
            raise ValueError("Too many page follows")

        url = "/api/v1/repository"

        # params
        params = {"namespace": self.organization}
        if page:
            params["next_page"] = page

        # perform request
        body = self._get(url, params=params)
        repositories = body.get("repositories", [])
        next_page = body.get("next_page")

        # append images
        if images is None:
            images = []

        images += repositories

        if next_page:
            return self.list_images(images, next_page, count + 1)
        return images

    def repo_create(self, repo_name: str, description: str, public: str) -> None:
        """Creates a repository called repo_name with the given description
        and public flag.

        :raise HTTPError: the operation fails
        """
        visibility = "public" if public else "private"

        url = "/api/v1/repository"

        params = {
            "repo_kind": "image",
            "namespace": self.organization,
            "visibility": visibility,
            "repository": repo_name,
            "description": description,
        }

        self._post(url, data=params)

    def repo_delete(self, repo_name: str) -> None:
        url = f"/api/v1/repository/{self.organization}/{repo_name}"
        self._delete(url)

    def repo_update_description(self, repo_name: str, description: str) -> None:
        url = f"/api/v1/repository/{self.organization}/{repo_name}"
        params = {"description": description}
        self._put(url, data=params)

    def repo_make_public(self, repo_name: str) -> None:
        self._repo_change_visibility(repo_name, "public")

    def repo_make_private(self, repo_name: str) -> None:
        self._repo_change_visibility(repo_name, "private")

    def _repo_change_visibility(self, repo_name: str, visibility: str) -> None:
        url = f"/api/v1/repository/{self.organization}/{repo_name}/changevisibility"
        params = {"visibility": visibility}
        self._post(url, data=params)

    def get_repo_team_permissions(self, repo_name: str, team: str) -> str | None:
        url = (
            f"/api/v1/repository/{self.organization}/"
            + f"{repo_name}/permissions/team/{team}"
        )
        try:
            body = self._get(url)
            return body.get("role") or None
        except requests.exceptions.HTTPError as e:
            message = ""
            if e.response is not None:
                with contextlib.suppress(ValueError, AttributeError):
                    message = e.response.json().get("message", "")

            expected_message = "Team does not have permission for repo."
            if message == expected_message:
                return None

            raise

    def set_repo_team_permissions(self, repo_name: str, team: str, role: str) -> None:
        url = (
            f"/api/v1/repository/{self.organization}/"
            + f"{repo_name}/permissions/team/{team}"
        )
        body = {"role": role}
        self._put(url, data=body)
