"""Quay repos reconciliation service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.quay_api import QuayApi, QuayRepo

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

if TYPE_CHECKING:
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class QuayReposConfigError(Exception):
    """Raised when org configuration is invalid (e.g. circular mirrors)."""


class QuayReposService:
    """Service for reconciling Quay repositories.

    Uses Dependency Injection to keep the service decoupled from secret backends.
    Talks directly to Layer 1 QuayApi — no caching layer needed (repos fetched
    once per run, no cross-task sharing).
    """

    def __init__(self, secret_manager: SecretManager) -> None:
        self.secret_manager = secret_manager

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

        desired: dict[QuayOrgKey, list[QuayRepoConfig]] = {}
        for org in org_map.values():
            if not org.managed_repos and not org.mirror:
                continue
            desired.setdefault(org.key, []).extend(org.repos)
            for downstream in downstream_of.get(org.key, []):
                desired.setdefault(downstream.key, []).extend(org.repos)

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
        api: QuayApi,
        org: QuayOrgConfig,
        actions: list[QuayRepoAction],
        applied_actions: list[QuayRepoAction],
        errors: list[str],
    ) -> None:
        for action in actions:
            try:
                self._execute_action(api, action)
                applied_actions.append(action)
            except Exception as e:
                error_msg = f"{org.instance}/{org.org_name}/{action.action_type}: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)

    @staticmethod
    def _execute_action(api: QuayApi, action: QuayRepoAction) -> None:
        match action:
            case QuayRepoActionCreate():
                logger.info(
                    f"Creating repo {action.instance}/{action.org_name}/{action.repo_name}",
                    action_type=action.action_type,
                )
                api.repo_create(
                    action.repo_name, action.description, public=action.public
                )

            case QuayRepoActionDelete():
                logger.info(
                    f"Deleting repo {action.instance}/{action.org_name}/{action.repo_name}",
                    action_type=action.action_type,
                )
                api.repo_delete(action.repo_name)

            case QuayRepoActionUpdateDescription():
                logger.info(
                    f"Updating description for {action.instance}/{action.org_name}/{action.repo_name}",
                    action_type=action.action_type,
                )
                api.repo_update_description(action.repo_name, action.description)

            case QuayRepoActionUpdateVisibility():
                logger.info(
                    f"Updating visibility for {action.instance}/{action.org_name}/{action.repo_name} public={action.public}",
                    action_type=action.action_type,
                )
                if action.public:
                    api.repo_make_public(action.repo_name)
                else:
                    api.repo_make_private(action.repo_name)

    # ------------------------------------------------------------------
    # Per-org reconciliation
    # ------------------------------------------------------------------

    def _reconcile_org(
        self,
        org: QuayOrgConfig,
        desired_repos: list[QuayRepoConfig],
        applied_actions: list[QuayRepoAction],
        errors: list[str],
        *,
        dry_run: bool,
    ) -> list[QuayRepoAction]:
        token = self.secret_manager.read(org.automation_token)
        with QuayApi(org=org.org_name, token=token, base_url=org.base_url) as api:
            current = api.list_images()
            actions = self._calculate_actions(org, current, desired_repos)
            if not dry_run:
                self._apply_actions(api, org, actions, applied_actions, errors)
        return actions

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
        applied_actions: list[QuayRepoAction] = []
        errors: list[str] = []

        for org_key, desired_repos in desired_by_org.items():
            org = org_map[org_key]
            logger.info(f"Reconciling {org.instance}/{org.org_name}")

            try:
                actions = self._reconcile_org(
                    org, desired_repos, applied_actions, errors, dry_run=dry_run
                )
                all_actions.extend(actions)
            except Exception as e:
                error_msg = f"{org.instance}/{org.org_name}: Unexpected error: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)

        return QuayReposTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
