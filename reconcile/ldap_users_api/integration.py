"""ldap-users-api: Delete orphaned users from app-interface and infra repos.

Client-orchestrated integration (no server-side service). Uses qontract-api
external endpoints for LDAP user checks and VCS merge request creation.
All YAML manipulation logic stays in the client.
"""

import asyncio
from functools import partial

import logging

import httpx
from qontract_api_client.api.external.ldap_users_check import (
    asyncio as check_ldap_users,
)
from qontract_api_client.api.external.vcs_create_merge_request import (
    asyncio as vcs_create_merge_request,
)
from qontract_api_client.api.external.vcs_find_merge_request import (
    asyncio as vcs_find_merge_request,
)
from qontract_api_client.api.external.vcs_get_file import asyncio as vcs_get_file
from qontract_api_client.models.create_merge_request_request import (
    CreateMergeRequestRequest,
)
from qontract_api_client.models.ldap_direct_secret import LdapDirectSecret
from qontract_api_client.models.ldap_users_check_request import LdapUsersCheckRequest
from qontract_api_client.models.secret import Secret

from reconcile.gql_definitions.common.users_with_paths import UserV1
from reconcile.ldap_users_api.models import PathSpec, PathType, UserPaths
from reconcile.ldap_users_api.mr_builder import (
    build_app_interface_file_operations,
    build_infra_file_operations,
)
from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.typed_queries.users_with_paths import get_users_with_paths
from reconcile.typed_queries.vcs import Vcs, get_vcs_instances
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)
from reconcile.utils.unleash.client import get_feature_toggle_state

logger = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "ldap-users-api"


class LdapUsersApiIntegrationParams(PydanticRunParams):
    """Parameters for LDAP users API integration."""

    app_interface_repo_url: str
    infra_repo_url: str
    infra_paths: list[str] = []
    labels: list[str] = []


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

    Client-orchestrated: queries GraphQL, checks LDAP via external endpoint,
    diffs locally, creates deletion MRs via VCS external endpoint.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def _find_existing_mr(
        self, *, repo_url: str, title: str, vcs_secret: Secret
    ) -> str | None:
        """Find an existing open MR by title.

        Returns MR URL if found, None if not (404).
        """
        try:
            response = await vcs_find_merge_request(
                client=self.qontract_api_client,
                secret_manager_url=vcs_secret.secret_manager_url,
                path=vcs_secret.path,
                field=vcs_secret.field,
                version=vcs_secret.version,
                repo_url=repo_url,
                title=title,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        return response.url

    async def _get_file_content(
        self, *, repo_url: str, path: str, vcs_secret: Secret
    ) -> str | None:
        """Read file content from a VCS repository via external endpoint.

        Returns None if the file does not exist (404).
        """
        try:
            response = await vcs_get_file(
                client=self.qontract_api_client,
                secret_manager_url=vcs_secret.secret_manager_url,
                path=vcs_secret.path,
                field=vcs_secret.field,
                version=vcs_secret.version,
                repo_url=repo_url,
                file_path=path,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        return response.content

    async def async_run(self, dry_run: bool) -> None:
        """Execute the LDAP users cleanup integration."""
        gqlapi = gql.get_api()

        # 1. Fetch desired state from GraphQL
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

        # 2. Check which users exist in LDAP via external endpoint
        ldap_response = await check_ldap_users(
            client=self.qontract_api_client,
            body=LdapUsersCheckRequest(
                usernames=usernames,
                secret=LdapDirectSecret(
                    secret_manager_url=self.secret_manager_url,
                    path=ldap_settings.credentials.path,
                    field=ldap_settings.credentials.field,
                    version=ldap_settings.credentials.version,
                    server_url=ldap_settings.server_url,
                    base_dn=ldap_settings.base_dn,
                ),
            ),
        )

        existing_users = {u.username for u in ldap_response.users or [] if u.exists}

        # 3. Safety check
        if usernames and not existing_users:
            raise RuntimeError(
                "LDAP returned empty result set - aborting to prevent mass deletion"
            )

        # 4. Diff
        users_to_delete = [
            u for u in users_with_paths if u.username not in existing_users
        ]
        if not users_to_delete:
            return

        for user in users_to_delete:
            logger.info(["delete_user", user.username])

        # 5. Create MRs (non-dry-run only)
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

        await self._delete_users_app_interface(
            users_to_delete,
            vcs_secret=app_interface_vcs_secret,
            dry_run=dry_run,
            auto_merge=auto_merge,
        )
        await self._delete_users_infra(
            [u.username for u in users_to_delete],
            vcs_secret=infra_vcs_secret,
            dry_run=dry_run,
            auto_merge=auto_merge,
        )

    async def _delete_users_app_interface(
        self,
        users: list[UserPaths],
        *,
        vcs_secret: Secret,
        dry_run: bool,
        auto_merge: bool,
    ) -> None:
        """Create one MR per user to delete from app-interface."""
        titles = [
            (user, f"[create_delete_user_mr] delete user {user.username}")
            for user in users
        ]

        # Dedup: check existing MRs in parallel by title
        existing_mrs = await asyncio.gather(*[
            self._find_existing_mr(
                repo_url=self.params.app_interface_repo_url,
                title=title,
                vcs_secret=vcs_secret,
            )
            for _, title in titles
        ])

        get_file = partial(
            self._get_file_content,
            repo_url=self.params.app_interface_repo_url,
            vcs_secret=vcs_secret,
        )

        mr_calls = []
        for (user, title), existing_mr_url in zip(titles, existing_mrs, strict=True):
            if existing_mr_url:
                logger.info(f"MR already exists for {user.username}: {existing_mr_url}")
                continue

            file_ops = await build_app_interface_file_operations(
                user=user,
                vcs_get_file=get_file,
                commit_message=title,
            )
            if not file_ops:
                continue

            if not dry_run:
                mr_calls.append(
                    vcs_create_merge_request(
                        client=self.qontract_api_client,
                        body=CreateMergeRequestRequest(
                            repo_url=self.params.app_interface_repo_url,
                            token=vcs_secret,
                            title=title,
                            description=f"delete user {user.username}",
                            file_operations=file_ops,
                            labels=self.params.labels,
                            auto_merge=auto_merge,
                        ),
                    )
                )

        error = False
        if mr_calls:
            results = await asyncio.gather(*mr_calls, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Failed to create MR: {result}")
                    error = True
        if error:
            raise RuntimeError("One or more MR creations failed")

    async def _delete_users_infra(
        self,
        usernames: list[str],
        *,
        vcs_secret: Secret,
        dry_run: bool,
        auto_merge: bool,
    ) -> None:
        """Create single MR to delete all users from infra repo."""
        title = "[create_ssh_key_mr] delete user(s)"

        # Dedup by title
        if existing_mr_url := await self._find_existing_mr(
            repo_url=self.params.infra_repo_url,
            title=title,
            vcs_secret=vcs_secret,
        ):
            logger.info(f"Infra MR already exists: {existing_mr_url}")
            return

        get_file = partial(
            self._get_file_content,
            repo_url=self.params.infra_repo_url,
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
            await vcs_create_merge_request(
                client=self.qontract_api_client,
                body=CreateMergeRequestRequest(
                    repo_url=self.params.infra_repo_url,
                    token=vcs_secret,
                    title=title,
                    description="delete user(s)",
                    file_operations=file_ops,
                    labels=self.params.labels,
                    auto_merge=auto_merge,
                ),
            )
