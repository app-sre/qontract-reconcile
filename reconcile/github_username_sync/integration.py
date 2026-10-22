"""github-username-sync: Sync github_username on internal App-Interface users from LDAP.

Compares each internal user's github_username against the GitHub account they
linked in their Rover profile (resolved via LDAP's rhatSocialURL attribute,
exposed through qontract-api's external LDAP endpoint) and proposes
corrections for stale/mistyped values through a single, batched app-interface
MR. Follows the same fail-safes as ldap-users-api: dry-run by default,
auto-merge gated behind an Unleash toggle, and suppressed above a
configurable threshold to limit merge-queue/CI blast radius.
"""

from __future__ import annotations

import logging
from functools import partial

from pydantic import Field
from qontract_api_client.client import (
    ldap_org_github_usernames,
    vcs_file_sync,
    vcs_get_file,
)
from qontract_api_client.exceptions import HTTPStatusError
from qontract_api_client.schemas import (
    FileSyncRequest,
    FileSyncStatus,
    LdapDirectSecret,
    LdapOrgGithubUsernamesRequest,
    Secret,
)

from reconcile.github_username_sync.models import GithubUsernameUpdate
from reconcile.github_username_sync.mr_builder import (
    build_github_username_update_operations,
)
from reconcile.gql_definitions.github_username_sync.users import (
    UserV1,
)
from reconcile.gql_definitions.github_username_sync.users import (
    query as query_users,
)
from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.typed_queries.vcs import Vcs, get_vcs_instances
from reconcile.utils import gql
from reconcile.utils.mr.labels import SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)
from reconcile.utils.unleash.client import get_feature_toggle_state

logger = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "github-username-sync"


class GithubUsernameSyncParams(PydanticRunParams):
    """Parameters for the github-username-sync integration."""

    app_interface_repo_url: str
    app_interface_target_branch: str = "master"
    labels: list[str] = Field(default_factory=list)
    auto_merge_threshold: int = 10


def _find_vcs_secret(
    secret_manager_url: str, vcs_instances: list[Vcs], repo_url: str
) -> Secret:
    """Find the VCS secret for a given repo URL from VCS instances.

    Raises:
        ValueError: If no matching VCS instance found
    """
    for vcs in vcs_instances:
        if repo_url.startswith(vcs.url):
            return Secret(
                secret_manager_url=secret_manager_url,
                path=vcs.token.path,
                field=vcs.token.field,
                version=vcs.token.version,
            )
    raise ValueError(f"No VCS instance found for repo URL: {repo_url}")


def compute_updates(
    users: list[UserV1],
    org_username_to_github: dict[str, str],
) -> list[GithubUsernameUpdate]:
    """Compare internal users against the LDAP-sourced GitHub mapping.

    Args:
        users: Internal app-interface users (org_username, path, github_username)
        org_username_to_github: org_username -> GitHub login, resolved via LDAP

    Returns:
        Users whose stored github_username genuinely differs (case-insensitively)
        from the LDAP-linked login. Users with no LDAP mapping, or whose stored
        value differs only in case, are left untouched - LDAP only yields a
        lowercased login, not GitHub's canonically-cased spelling, so a
        case-only mismatch cannot be corrected with confidence here.
    """
    updates = []
    for user in users:
        if not (ldap_github_username := org_username_to_github.get(user.org_username)):
            continue
        if ldap_github_username.lower() == user.github_username.lower():
            continue
        updates.append(
            GithubUsernameUpdate(
                org_username=user.org_username,
                path=user.path,
                current_github_username=user.github_username,
                github_username=ldap_github_username,
            )
        )
    return updates


class GithubUsernameSyncIntegration(
    QontractReconcileApiIntegration[GithubUsernameSyncParams]
):
    """Sync github_username on internal app-interface users from LDAP.

    Queries GraphQL for internal users, resolves their Rover-linked GitHub
    account via qontract-api's external LDAP endpoint, diffs locally, and
    reconciles via the VCS file-sync endpoint.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def async_run(self, dry_run: bool) -> None:
        """Execute the github-username-sync integration."""
        gqlapi = gql.get_api()

        users = query_users(query_func=gqlapi.query).users or []
        if not users:
            return

        ldap_settings = get_ldap_settings(query_func=gqlapi.query)
        if not ldap_settings.credentials:
            raise RuntimeError("LDAP credentials not found in settings")

        with self.log_api_exceptions():
            ldap_response = await ldap_org_github_usernames(
                LdapOrgGithubUsernamesRequest(
                    secret=LdapDirectSecret(
                        secret_manager_url=self.secret_manager_url,
                        path=ldap_settings.credentials.path,
                        field=ldap_settings.credentials.field,
                        version=ldap_settings.credentials.version,
                        server_urls=ldap_settings.server_urls,
                        base_dn=ldap_settings.base_dn,
                    ),
                ),
            )

        org_username_to_github = {
            u.org_username: u.github_username for u in ldap_response.users
        }

        updates = compute_updates(users, org_username_to_github)
        if not updates:
            return

        for update in updates:
            logger.info(
                f"update_github_username: {update.org_username} "
                f"{update.current_github_username!r} -> {update.github_username!r}"
            )

        if dry_run:
            return

        vcs_instances = get_vcs_instances(query_func=gqlapi.query)
        vcs_secret = _find_vcs_secret(
            self.secret_manager_url, vcs_instances, self.params.app_interface_repo_url
        )

        auto_merge = get_feature_toggle_state(
            integration_name=f"{self.name}-allow-auto-merge-mrs",
            default=False,
        )
        labels = list(self.params.labels)
        if len(updates) > self.params.auto_merge_threshold:
            logger.warning(
                f"{len(updates)} github_username updates exceeds auto-merge "
                f"threshold ({self.params.auto_merge_threshold}) - suppressing "
                "auto-merge, manual review required"
            )
            auto_merge = False
            labels.append(SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE)

        await self._sync_github_usernames(
            updates,
            vcs_secret=vcs_secret,
            auto_merge=auto_merge,
            labels=labels,
        )

    async def _get_file_content(self, *, path: str, vcs_secret: Secret) -> str | None:
        """Read file content from the app-interface repository.

        Returns None if the file does not exist (404).
        """
        try:
            response = await vcs_get_file(
                secret_manager_url=vcs_secret.secret_manager_url,
                path=vcs_secret.path,
                field=vcs_secret.field,
                version=vcs_secret.version,
                repo_url=self.params.app_interface_repo_url,
                file_path=path,
                ref=self.params.app_interface_target_branch,
            )
        except HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        return response.content

    async def _sync_github_usernames(
        self,
        updates: list[GithubUsernameUpdate],
        *,
        vcs_secret: Secret,
        auto_merge: bool,
        labels: list[str],
    ) -> None:
        """Create a single MR correcting github_username for all affected users."""
        title = "[github_username_sync] sync github_username from LDAP"
        get_file = partial(self._get_file_content, vcs_secret=vcs_secret)

        file_ops = await build_github_username_update_operations(
            updates=updates,
            vcs_get_file=get_file,
            commit_message=title,
        )
        if not file_ops:
            return

        response = await vcs_file_sync(
            FileSyncRequest(
                repo_url=self.params.app_interface_repo_url,
                token=vcs_secret,
                title=title,
                description=(
                    f"sync github_username from LDAP for {len(updates)} user(s): "
                    f"{', '.join(u.org_username for u in updates)}"
                ),
                target_branch=self.params.app_interface_target_branch,
                file_operations=file_ops,
                labels=labels,
                auto_merge=auto_merge,
            ),
        )
        match response.status:
            case FileSyncStatus.MR_CREATED:
                logger.info(f"MR created: {response.mr_url}")
            case FileSyncStatus.MR_EXISTS:
                logger.info(f"MR already exists: {response.mr_url}")
