"""Quay repos reconciliation service."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

from qontract_utils.quay_api import QuayRepo

from qontract_api.integrations.quay_repos.schemas import (
    QuayOrgConfig,
    QuayOrgKey,
    QuayRepoAction,
    QuayRepoActionCreate,
    QuayRepoActionDelete,
    QuayRepoActionUpdateDescription,
    QuayRepoActionUpdateVisibility,
    QuayRepoConfig,
    QuayReposTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.quay.quay_client_factory import create_quay_workspace_client

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.quay.quay_workspace_client import QuayWorkspaceClient
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class QuayReposConfigError(Exception):
    """Raised when org configuration is invalid (e.g. circular mirrors)."""


class QuayReposService:
    """Service for reconciling Quay repositories.

    Uses Dependency Injection to keep the service decoupled from secret backends.
    Talks to Layer 2 QuayWorkspaceClient — never calls Layer 1 QuayApi directly.
    """

    def __init__(
        self,
        secret_manager: SecretManager,
        cache: CacheBackend,
        settings: Settings,
        workspace_client_factory: Callable[..., QuayWorkspaceClient] | None = None,
    ) -> None:
        self.secret_manager = secret_manager
        self.cache = cache
        self.settings = settings
        self._workspace_client_factory = workspace_client_factory or create_quay_workspace_client

    # ------------------------------------------------------------------
    # Consistency checks
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_org_configs(org_map: dict[QuayOrgKey, QuayOrgConfig]) -> None:
        """Validate org configurations before reconciliation.

        Raises:
            QuayReposConfigError: on circular mirror dependency,
                org having both managed_repos and mirror set, or
                mirror org whose upstream is absent from the payload.
        """
        for org in org_map.values():
            if org.mirror and org.managed_repos:
                raise QuayReposConfigError(
                    f"{org.instance}/{org.org_name} has both mirror and managed_repos set"
                )
            if org.mirror:
                if org.mirror not in org_map:
                    raise QuayReposConfigError(
                        f"{org.instance}/{org.org_name}: upstream org "
                        f"{org.mirror.instance}/{org.mirror.org_name} is absent from the "
                        "payload; cannot reconcile mirror without upstream repos"
                    )
                mirror_org = org_map.get(org.mirror)
                if mirror_org and mirror_org.mirror:
                    raise QuayReposConfigError(
                        f"{org.mirror.instance}/{org.mirror.org_name} "
                        "cannot have mirrors and be a mirror itself"
                    )

    # ------------------------------------------------------------------
    # Mirror expansion
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_desired_state(
        org_map: dict[QuayOrgKey, QuayOrgConfig],
    ) -> dict[QuayOrgKey, list[QuayRepoConfig]]:
        """Build desired state per org, propagating repos to mirror orgs."""
        downstream_of: dict[QuayOrgKey, list[QuayOrgConfig]] = {}
        for org in org_map.values():
            if org.mirror:
                downstream_of.setdefault(org.mirror, []).append(org)

        for upstream_key, downstreams in downstream_of.items():
            if upstream_key not in org_map:
                referencing = ", ".join(
                    f"{d.instance}/{d.org_name}" for d in downstreams
                )
                raise QuayReposConfigError(
                    f"Mirror upstream {upstream_key.instance}/{upstream_key.org_name} is "
                    f"absent from the reconciliation payload (referenced by: {referencing}). "
                    f"Include the upstream org or remove the mirror reference."
                )

        desired: dict[QuayOrgKey, list[QuayRepoConfig]] = {}
        for org in org_map.values():
            if not org.managed_repos and not org.mirror:
                continue
            desired.setdefault(org.key, []).extend(org.repos)
            for downstream in downstream_of.get(org.key, []):
                desired.setdefault(downstream.key, []).extend(org.repos)

        for org_key, repos in desired.items():
            counts = Counter(r.name for r in repos)
            dupes = [name for name, count in counts.items() if count > 1]
            if dupes:
                raise QuayReposConfigError(
                    f"{org_key.instance}/{org_key.org_name}: duplicate repo names after "
                    f"mirror expansion: {sorted(dupes)}"
                )

        return desired

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_actions(
        org: QuayOrgConfig,
        current: list[QuayRepo],
        desired: list[QuayRepoConfig],
    ) -> list[QuayRepoAction]:
        current_map = {r.name: r for r in current}
        desired_map = {r.name: r for r in desired}
        actions: list[QuayRepoAction] = []

        # Delete repos that are not in the desired state
        actions.extend([
            QuayRepoActionDelete(
                instance=org.instance,
                org_name=org.org_name,
                repo_name=name,
            )
            for name in current_map
            if name not in desired_map
        ])

        # Create repos that are not in the current state
        actions.extend([
            QuayRepoActionCreate(
                instance=org.instance,
                org_name=org.org_name,
                repo_name=name,
                public=desired_repo.public,
                description=desired_repo.description,
            )
            for name, desired_repo in desired_map.items()
            if name not in current_map
        ])

        for name, desired_repo in desired_map.items():
            current_repo = current_map.get(name)
            if current_repo is None:
                continue  # already handled by the create comprehension above
            if current_repo.is_public != desired_repo.public:
                actions.append(
                    QuayRepoActionUpdateVisibility(
                        instance=org.instance,
                        org_name=org.org_name,
                        repo_name=name,
                        public=desired_repo.public,
                    )
                )
            if current_repo.description != desired_repo.description:
                actions.append(
                    QuayRepoActionUpdateDescription(
                        instance=org.instance,
                        org_name=org.org_name,
                        repo_name=name,
                        description=desired_repo.description,
                    )
                )

        return actions

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def _apply_actions(
        self,
        client: QuayWorkspaceClient,
        org: QuayOrgConfig,
        actions: list[QuayRepoAction],
    ) -> tuple[list[QuayRepoAction], list[str]]:
        applied: list[QuayRepoAction] = []
        errors: list[str] = []
        for action in actions:
            try:
                self._execute_action(client, action)
                applied.append(action)
            except Exception as e:
                error_msg = f"{org.instance}/{org.org_name}/{action.action_type}: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)
        return applied, errors

    @staticmethod
    def _execute_action(client: QuayWorkspaceClient, action: QuayRepoAction) -> None:
        match action:
            case QuayRepoActionCreate():
                logger.info(
                    f"Creating repo {action.instance}/{action.org_name}/{action.repo_name}",
                    action_type=action.action_type,
                )
                client.repo_create(
                    action.repo_name, action.description, public=action.public
                )

            case QuayRepoActionDelete():
                logger.info(
                    f"Deleting repo {action.instance}/{action.org_name}/{action.repo_name}",
                    action_type=action.action_type,
                )
                client.repo_delete(action.repo_name)

            case QuayRepoActionUpdateDescription():
                logger.info(
                    f"Updating description for {action.instance}/{action.org_name}/{action.repo_name}",
                    action_type=action.action_type,
                )
                client.repo_update_description(action.repo_name, action.description)

            case QuayRepoActionUpdateVisibility():
                logger.info(
                    f"Updating visibility for {action.instance}/{action.org_name}/{action.repo_name} public={action.public}",
                    action_type=action.action_type,
                )
                if action.public:
                    client.repo_make_public(action.repo_name)
                else:
                    client.repo_make_private(action.repo_name)

    # ------------------------------------------------------------------
    # Per-org reconciliation
    # ------------------------------------------------------------------

    def _reconcile_org(
        self,
        org: QuayOrgConfig,
        desired_repos: list[QuayRepoConfig],
        *,
        dry_run: bool,
    ) -> tuple[list[QuayRepoAction], list[QuayRepoAction], list[str]]:
        with self._workspace_client_factory(
            secret=org.automation_token,
            org_name=org.org_name,
            base_url=org.base_url,
            cache=self.cache,
            secret_manager=self.secret_manager,
            settings=self.settings,
        ) as client:
            current = client.get_repos()
            actions = self._calculate_actions(org, current, desired_repos)
            if not dry_run:
                applied, errors = self._apply_actions(client, org, actions)
            else:
                applied, errors = [], []
        return actions, applied, errors

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def reconcile(
        self,
        orgs: list[QuayOrgConfig],
        *,
        dry_run: bool = True,
    ) -> QuayReposTaskResult:
        """Reconcile Quay repositories across all provided orgs.

        Raises:
            QuayReposConfigError: on invalid org configuration (fails entire task).
        """
        org_map = {org.key: org for org in orgs}
        self._validate_org_configs(org_map)

        desired_by_org = self._expand_desired_state(org_map)

        all_actions: list[QuayRepoAction] = []
        all_applied: list[QuayRepoAction] = []
        all_errors: list[str] = []

        for org_key, desired_repos in desired_by_org.items():
            org = org_map[org_key]
            logger.info(f"Reconciling {org.instance}/{org.org_name}")

            try:
                actions, applied, errors = self._reconcile_org(
                    org, desired_repos, dry_run=dry_run
                )
                all_actions.extend(actions)
                all_applied.extend(applied)
                all_errors.extend(errors)
            except Exception as e:
                error_msg = f"{org.instance}/{org.org_name}: Unexpected error: {e}"
                logger.exception(error_msg)
                all_errors.append(error_msg)

        return QuayReposTaskResult(
            status=TaskStatus.FAILED if all_errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=all_applied,
            applied_count=len(all_applied),
            errors=all_errors,
        )
