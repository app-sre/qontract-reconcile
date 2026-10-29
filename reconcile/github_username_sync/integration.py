"""github-username-sync: Sync github_username on internal App-Interface users from LDAP.

Compares each internal user's github_username against the GitHub account they
linked in their Rover profile (resolved via LDAP's rhatSocialURL attribute,
exposed through qontract-api's external LDAP endpoint) and proposes
corrections through a single, batched app-interface MR.

LDAP's rhatSocialURL is untrusted: it may reference a GitHub account that no
longer exists, a GitHub organization instead of a personal account, or only
ever carries a lowercased login. Every LDAP-linked login is therefore
re-validated against the GitHub API (qontract-api's external GitHub
endpoint) before being proposed as an update - this both filters out
non-existent/organization accounts and supplies the canonical casing needed
to correct case-only mismatches.

Follows the same fail-safes as ldap-users-api: dry-run by default, auto-merge
gated behind an Unleash toggle, and suppressed above a configurable threshold
to limit merge-queue/CI blast radius.
"""

from __future__ import annotations

import logging
from functools import partial

from pydantic import Field
from qontract_api_client.client import (
    github_users_validate,
    ldap_org_github_usernames,
    vcs_file_sync,
    vcs_get_file,
)
from qontract_api_client.exceptions import HTTPStatusError
from qontract_api_client.schemas import (
    FileSyncRequest,
    FileSyncStatus,
    GithubAccountType,
    GithubUsersValidateRequest,
    LdapDirectSecret,
    LdapOrgGithubUsernamesRequest,
    Secret,
)
from qontract_utils.vcs import normalize_app_interface_path

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
from reconcile.typed_queries.github_orgs import get_github_orgs
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


def _find_default_github_secret(secret_manager_url: str) -> Secret:
    """Find the default GitHub org's API token, used for username validation.

    Raises:
        ValueError: If no default GitHub org is configured
    """
    for org in get_github_orgs():
        if org.default:
            return Secret(
                secret_manager_url=secret_manager_url,
                path=org.token.path,
                field=org.token.field,
                version=org.token.version,
            )
    raise ValueError("No default GitHub org configured")


def compute_updates(
    users: list[UserV1],
    org_username_to_github: dict[str, str],
) -> list[GithubUsernameUpdate]:
    """Compare internal users against the GitHub-validated LDAP mapping.

    Args:
        users: Internal app-interface users (org_username, path, github_username)
        org_username_to_github: org_username -> canonical GitHub login, resolved
            via LDAP's rhatSocialURL and confirmed to exist (as a personal
            account) via the GitHub API

    Returns:
        Users whose stored github_username differs from the canonical GitHub
        login - including case-only differences, since the mapping now carries
        GitHub's own canonical casing. Users with no validated mapping are
        left untouched.
    """
    updates = []
    for user in users:
        if not (github_username := org_username_to_github.get(user.org_username)):
            continue
        if github_username == user.github_username:
            continue
        updates.append(
            GithubUsernameUpdate(
                org_username=user.org_username,
                path=normalize_app_interface_path(user.path),
                current_github_username=user.github_username,
                github_username=github_username,
            )
        )
    return updates


class GithubUsernameSyncIntegration(
    QontractReconcileApiIntegration[GithubUsernameSyncParams]
):
    """Sync github_username on internal app-interface users from LDAP.

    Queries GraphQL for internal users, resolves their Rover-linked GitHub
    account via qontract-api's external LDAP endpoint, validates each
    resolved login against the GitHub API (existence + canonical casing) via
    qontract-api's external GitHub endpoint, diffs locally, and reconciles
    via the VCS file-sync endpoint.
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

        org_username_to_ldap_login = {
            u.org_username: u.github_username for u in ldap_response.users
        }

        if unresolved := sorted(
            user.org_username
            for user in users
            if user.org_username not in org_username_to_ldap_login
        ):
            logger.warning(
                "no unambiguous LDAP-linked GitHub account found; "
                f"leaving github_username unchanged for: {', '.join(unresolved)}"
            )

        canonical_logins: dict[str, str] = {}
        if org_username_to_ldap_login:
            github_secret = _find_default_github_secret(self.secret_manager_url)
            with self.log_api_exceptions():
                validate_response = await github_users_validate(
                    GithubUsersValidateRequest(
                        secret=github_secret,
                        usernames=sorted(set(org_username_to_ldap_login.values())),
                        account_type=GithubAccountType.USER,
                    ),
                )
            canonical_logins = {
                u.login.lower(): u.login for u in validate_response.users
            }

        org_username_to_github: dict[str, str] = {}
        invalid_ldap_logins: set[str] = set()
        for org_username, ldap_login in org_username_to_ldap_login.items():
            if canonical := canonical_logins.get(ldap_login.lower()):
                org_username_to_github[org_username] = canonical
            else:
                invalid_ldap_logins.add(ldap_login)

        if invalid_ldap_logins:
            logger.warning(
                "LDAP-linked GitHub account does not exist or is not a "
                "personal account; leaving github_username unchanged for "
                f"LDAP-linked login(s): {', '.join(sorted(invalid_ldap_logins))}"
            )

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
