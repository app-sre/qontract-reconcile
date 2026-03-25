"""GitHub owners reconciliation service.

Handles fetching current state from GitHub, computing diffs against desired
state, and executing add-owner actions.

Note: Owner removal is intentionally NOT supported. Only add_owner actions are
generated. This preserves the behavior of the original github-owners reconcile
integration, where removing org admins requires explicit manual review.
"""

from qontract_utils.differ import diff_iterables

from qontract_api.config import Settings
from qontract_api.github import GithubOrgClientFactory, GithubOrgWorkspaceClient
from qontract_api.integrations.github_owners.domain import GithubOrgDesiredState
from qontract_api.integrations.github_owners.schemas import (
    GithubOwnerActionAddOwner,
    GithubOwnersTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class GithubOwnersService:
    """Service for reconciling GitHub organization owner membership.

    Fetches current org admin membership from GitHub, computes the diff
    against the desired state, and executes add-owner actions.

    Owner removal is intentionally not supported — see schemas.py for rationale.

    Uses Dependency Injection to keep the service decoupled from implementation
    details (ADR-011).
    """

    def __init__(
        self,
        github_org_client_factory: GithubOrgClientFactory,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        """Initialize service.

        Args:
            github_org_client_factory: Factory for creating GithubOrgWorkspaceClient instances
            secret_manager: Secret backend for retrieving GitHub tokens
            settings: Application settings
        """
        self.github_org_client_factory = github_org_client_factory
        self.secret_manager = secret_manager
        self.settings = settings

    def _create_github_org_client(
        self, org: GithubOrgDesiredState
    ) -> GithubOrgWorkspaceClient:
        """Create a GithubOrgWorkspaceClient for the given org.

        Args:
            org: Desired state for the org (includes token reference and base_url)

        Returns:
            GithubOrgWorkspaceClient with caching layer
        """
        token = self.secret_manager.read(org.token)
        return self.github_org_client_factory.create_workspace_client(
            token=token,
            base_url=org.base_url,
        )

    @staticmethod
    def _calculate_actions(
        org: GithubOrgDesiredState,
        github_client: GithubOrgWorkspaceClient,
    ) -> list[GithubOwnerActionAddOwner]:
        """Calculate add-owner actions for a single org.

        Fetches current state (admin members + pending invitations) and diffs
        against desired owners. Only generates add_owner actions — owner removal
        is intentionally not supported.

        Args:
            org: Desired state for the org
            github_client: Workspace client for the org

        Returns:
            List of add_owner actions for users in desired but not in current state
        """
        current_members = github_client.get_current_members(org.org_name)

        # diff_iterables identifies items in desired but not current (add set)
        diff = diff_iterables(
            current=current_members,
            desired=org.owners,
            key=lambda username: username,
        )

        return [
            GithubOwnerActionAddOwner(org_name=org.org_name, username=username)
            for username in diff.add
        ]

    @staticmethod
    def _execute_action(
        github_client: GithubOrgWorkspaceClient,
        action: GithubOwnerActionAddOwner,
    ) -> None:
        """Execute a single add-owner action.

        Args:
            github_client: Workspace client for the org
            action: The add_owner action to execute
        """
        logger.info(
            f"Adding owner: {action.username} to org {action.org_name}",
            action_type=action.action_type,
            org_name=action.org_name,
            username=action.username,
        )
        github_client.add_member_as_admin(action.org_name, action.username)

    def reconcile(
        self,
        organizations: list[GithubOrgDesiredState],
        *,
        dry_run: bool = True,
    ) -> GithubOwnersTaskResult:
        """Reconcile GitHub organization owner membership.

        Main reconciliation logic: compare desired state vs current state,
        calculate diff, and execute add-owner actions (if dry_run=False).

        Owner removal is intentionally not supported. See schemas.py for
        the rationale.

        Args:
            organizations: List of orgs with desired owner membership
            dry_run: If True, only calculate actions without executing (keyword-only)

        Returns:
            GithubOwnersTaskResult with actions, applied_count, and errors
        """
        all_actions: list[GithubOwnerActionAddOwner] = []
        applied_actions: list[GithubOwnerActionAddOwner] = []
        errors: list[str] = []

        for org in organizations:
            logger.info(f"Reconciling GitHub org: {org.org_name}")

            try:
                github_client = self._create_github_org_client(org)
                org_actions = self._calculate_actions(org, github_client)
                all_actions.extend(org_actions)
            except Exception as e:
                error_msg = (
                    f"{org.org_name}: Unexpected error during diff calculation: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)
                continue

            if not dry_run and org_actions:
                for action in org_actions:
                    try:
                        self._execute_action(github_client, action)
                        applied_actions.append(action)
                    except Exception as e:
                        error_msg = (
                            f"{action.org_name}/{action.username}: "
                            f"Failed to execute {action.action_type}: {e}"
                        )
                        logger.exception(error_msg)
                        errors.append(error_msg)

        return GithubOwnersTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
