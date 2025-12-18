from collections.abc import Callable

from qontract_utils.secret_reader import SecretBackend

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.vcs.vcs_workspace_client import VCSWorkspaceClient
from qontract_api.integrations.slack_usergroups_v2.models import SlackUsergroupsUser


class UserSourceGitOwnersResolver:
    def __init__(
        self,
        users: list[SlackUsergroupsUser],
        cache: CacheBackend,
        secret_reader: SecretBackend,
        settings: Settings,
        vcs_workspace_client_builder: Callable[..., VCSWorkspaceClient],
    ):
        self.cache = cache
        self.secret_reader = secret_reader
        self.settings = settings
        self.vcs_workspace_client_builder = vcs_workspace_client_builder
        self.user_by_github_username = {
            user.github_username.lower(): user for user in users
        }
        self.user_by_org_username = {user.org_username.lower(): user for user in users}

    def resolve(self, git_url: str) -> set[str]:
        # allow passing repo_url:ref to select different branch
        if git_url.count(":") == 2:
            url, ref = git_url.rsplit(":", 1)
        else:
            url, ref = git_url, "master"

        # TODO: client reuse and cleanup
        client = self.vcs_workspace_client_builder(
            repo_url=url,
            cache=self.cache,
            secret_reader=self.secret_reader,
            settings=self.settings,
        )

        owners = client.get_owners(path="/", ref=ref)

        owner_names = (owners.approvers or []) + (owners.reviewers or [])
        users_map = (
            self.user_by_github_username
            if client.provider_name == "github"
            else self.user_by_org_username
        )
        return {
            user.org_username
            for owner_name in owner_names
            if (user := users_map.get(owner_name.lower()))
            and user.tag_on_merge_requests is not False
        }
