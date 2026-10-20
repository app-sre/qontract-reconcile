"""ldap-users-api: Delete orphaned users from app-interface and infra repos.

Uses qontract-api file-sync endpoint for VCS reconciliation.
All YAML manipulation logic stays in the client.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from pydantic import Field
from qontract_api_client.client import ldap_users_check as check_ldap_users
from qontract_api_client.client import (
    vcs_file_sync,
    vcs_get_file,
)
from qontract_api_client.exceptions import HTTPStatusError
from qontract_api_client.schemas import (
    FileSyncRequest,
    FileSyncStatus,
    LdapDirectSecret,
    LdapUsersCheckRequest,
    Secret,
)

from reconcile.ldap_users_api.models import PathSpec, PathType, UserPaths
from reconcile.ldap_users_api.mr_builder import (
    build_batched_app_interface_file_operations,
    build_infra_file_operations,
)
from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.typed_queries.users_with_paths import get_users_with_paths
from reconcile.typed_queries.vcs import Vcs, get_vcs_instances
from reconcile.utils import gql
from reconcile.utils.mr.labels import SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)
from reconcile.utils.unleash.client import get_feature_toggle_state

if TYPE_CHECKING:
    from reconcile.gql_definitions.common.users_with_paths import UserV1
logger = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "ldap-users-api"


class LdapUsersApiIntegrationParams(PydanticRunParams):
    """Parameters for LDAP users API integration."""

    app_interface_repo_url: str
    app_interface_target_branch: str = "master"
    infra_repo_url: str
    infra_target_branch: str = "master"
    infra_paths: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    auto_merge_threshold: int = 10


def transform_users_with_paths(users_with_paths: list[UserV1]) -> list[UserPaths]:
    """Convert GraphQL UserV1 objects into UserPaths models."""
    result = []
    for user in users_with_paths:
        paths = [PathSpec(type=PathType.USER, path=user.path)]
        paths.extend(
            PathSpec(type=PathType.REQUEST, path=r.path) for r in user.requests or []
        )
        paths.extend(
            PathSpec(type=PathType.QUERY, path=q.path) for q in user.queries or []
        )
        paths.extend(
            PathSpec(type=PathType.GABI, path=g.path) for g in user.gabi_instances or []
        )
        paths.extend(
            PathSpec(type=PathType.AWS_ACCOUNTS, path=a.path)
            for a in user.aws_accounts or []
        )
        paths.extend(
            PathSpec(type=PathType.SCHEDULE, path=s.path) for s in user.schedules or []
        )
        paths.extend(
            PathSpec(type=PathType.SRE_CHECKPOINT, path=s.path)
            for s in user.sre_checkpoints or []
        )
        result.append(UserPaths(username=user.org_username, paths=paths))
    return result


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


class LdapUsersApiIntegration(
    QontractReconcileApiIntegration[LdapUsersApiIntegrationParams]
):
    """Delete orphaned users from app-interface/infra repos.

    Queries GraphQL, checks LDAP via external endpoint,
    diffs locally, reconciles via VCS file-sync endpoint.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def _get_file_content(
        self, *, repo_url: str, path: str, ref: str, vcs_secret: Secret
    ) -> str | None:
        """Read file content from a VCS repository via external endpoint.

        Returns None if the file does not exist (404).
        """
        try:
            response = await vcs_get_file(
                secret_manager_url=vcs_secret.secret_manager_url,
                path=vcs_secret.path,
                field=vcs_secret.field,
                version=vcs_secret.version,
                repo_url=repo_url,
                file_path=path,
                ref=ref,
            )
        except HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        return response.content

    async def async_run(self, dry_run: bool) -> None:
        """Execute the LDAP users cleanup integration."""
        gqlapi = gql.get_api()

        users_with_paths = transform_users_with_paths(
            get_users_with_paths(query_func=gqlapi.query)
        )
        ldap_settings = get_ldap_settings(query_func=gqlapi.query)
        if not ldap_settings.credentials:
            raise RuntimeError("LDAP credentials not found in settings")

        vcs_instances = get_vcs_instances(query_func=gqlapi.query)
        usernames = [u.username for u in users_with_paths]
        if not usernames:
            return

        with self.log_api_exceptions():
            ldap_response = await check_ldap_users(
                LdapUsersCheckRequest(
                    usernames=usernames,
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

        existing_users = {u.username for u in ldap_response.users or [] if u.exists}

        if usernames and not existing_users:
            raise RuntimeError(
                "LDAP returned empty result set - aborting to prevent mass deletion"
            )

        users_to_delete = [
            u for u in users_with_paths if u.username not in existing_users
        ]
        if not users_to_delete:
            return

        for user in users_to_delete:
            logger.info(["delete_user", user.username])

        app_interface_vcs_secret = _find_vcs_secret(
            self.secret_manager_url, vcs_instances, self.params.app_interface_repo_url
        )
        infra_vcs_secret = _find_vcs_secret(
            self.secret_manager_url, vcs_instances, self.params.infra_repo_url
        )
        auto_merge = get_feature_toggle_state(
            integration_name=f"{self.name}-allow-auto-merge-mrs",
            default=False,
        )
        labels = list(self.params.labels)
        if len(users_to_delete) > self.params.auto_merge_threshold:
            logger.warning(
                f"{len(users_to_delete)} users to delete exceeds auto-merge "
                f"threshold ({self.params.auto_merge_threshold}) - suppressing "
                "auto-merge, manual review required"
            )
            auto_merge = False
            labels.append(SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE)

        await self._delete_users_app_interface(
            users_to_delete,
            vcs_secret=app_interface_vcs_secret,
            dry_run=dry_run,
            auto_merge=auto_merge,
            labels=labels,
        )
        await self._delete_users_infra(
            [u.username for u in users_to_delete],
            vcs_secret=infra_vcs_secret,
            dry_run=dry_run,
            auto_merge=auto_merge,
            labels=labels,
        )

    async def _delete_users_app_interface(
        self,
        users: list[UserPaths],
        *,
        vcs_secret: Secret,
        dry_run: bool,
        auto_merge: bool,
        labels: list[str],
    ) -> None:
        """Create a single MR to delete all users from app-interface via file-sync."""
        target_branch = self.params.app_interface_target_branch
        title = "[create_delete_user_mr] delete user(s)"
        usernames = [user.username for user in users]

        get_file = partial(
            self._get_file_content,
            repo_url=self.params.app_interface_repo_url,
            ref=target_branch,
            vcs_secret=vcs_secret,
        )

        file_ops = await build_batched_app_interface_file_operations(
            users=users,
            vcs_get_file=get_file,
            commit_message=title,
        )
        if not file_ops:
            logger.info("No app-interface files to update, skipping MR creation")
            return

        if dry_run:
            return

        response = await vcs_file_sync(
            FileSyncRequest(
                repo_url=self.params.app_interface_repo_url,
                token=vcs_secret,
                title=title,
                description=f"delete {len(usernames)} user(s): {', '.join(usernames)}",
                target_branch=target_branch,
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

    async def _delete_users_infra(
        self,
        usernames: list[str],
        *,
        vcs_secret: Secret,
        dry_run: bool,
        auto_merge: bool,
        labels: list[str],
    ) -> None:
        """Create single MR to delete all users from infra repo via file-sync."""
        title = "[create_ssh_key_mr] delete user(s)"
        target_branch = self.params.infra_target_branch

        get_file = partial(
            self._get_file_content,
            repo_url=self.params.infra_repo_url,
            ref=target_branch,
            vcs_secret=vcs_secret,
        )

        file_ops = await build_infra_file_operations(
            usernames=usernames,
            infra_paths=self.params.infra_paths,
            vcs_get_file=get_file,
            commit_message=title,
        )
        if not file_ops:
            logger.info("No users matched in infra repo, skipping MR creation")
            return

        if not dry_run:
            response = await vcs_file_sync(
                FileSyncRequest(
                    repo_url=self.params.infra_repo_url,
                    token=vcs_secret,
                    title=title,
                    description="delete user(s)",
                    target_branch=target_branch,
                    file_operations=file_ops,
                    labels=labels,
                    auto_merge=auto_merge,
                ),
            )
            match response.status:
                case FileSyncStatus.MR_CREATED:
                    logger.info(f"Infra MR created: {response.mr_url}")
                case FileSyncStatus.MR_EXISTS:
                    logger.info(f"Infra MR already exists: {response.mr_url}")
