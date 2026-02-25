"""Slack usergroups reconciliation service."""

from collections.abc import Iterable

from qontract_utils.differ import diff_iterables
from qontract_utils.secret_reader import Secret

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroup,
    SlackUsergroupAction,
    SlackUsergroupActionCreate,
    SlackUsergroupActionUpdateMetadata,
    SlackUsergroupActionUpdateUsers,
    SlackUsergroupsTaskResult,
    SlackWorkspace,
)
from qontract_api.slack.slack_client_factory import create_slack_workspace_client
from qontract_api.slack.slack_workspace_client import SlackWorkspaceClient
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class SlackUsergroupsService:
    """Service for reconciling Slack usergroups.

    Handles fetching current state from Slack, computing diffs against desired state,
    and executing reconciliation actions.

    Uses Dependency Injection to keep service decoupled from implementation details.
    """

    def __init__(
        self,
        cache: CacheBackend,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        """Initialize service.

        Args:
            cache: Cache backend for distributed caching and locking
            secret_manager: Secret backend for retrieving Slack tokens
            settings: Application settings
        """
        self.cache = cache
        self.secret_manager = secret_manager
        self.settings = settings

    def _create_slack_client(
        self, workspace_name: str, token: Secret
    ) -> SlackWorkspaceClient:
        """Create SlackWorkspaceClient with caching, locking, and rate limiting.

        Fetches token from secret backend and uses factory to create client.

        Args:
            workspace_name: Name of the Slack workspace
            token: Secret reference for Slack API token

        Returns:
            SlackWorkspaceClient instance with full caching + compute layer
        """
        return create_slack_workspace_client(
            secret=token,
            workspace_name=workspace_name,
            cache=self.cache,
            secret_manager=self.secret_manager,
            settings=self.settings,
        )

    @staticmethod
    def _execute_action(
        slack: SlackWorkspaceClient, action: SlackUsergroupAction
    ) -> None:
        """Execute a single action.

        Args:
            slack: SlackWorkspaceClient (Layer 2 - Cache + Compute)
            action: Action to execute

        Raises:
            SlackApiError: If Slack API call fails
        """
        # Type-safe pattern matching on action type
        match action:
            case SlackUsergroupActionCreate():
                logger.info(
                    f"Creating usergroup: {action.workspace}/{action.usergroup}",
                    action_type=action.action_type,
                    workspace=action.workspace,
                    usergroup=action.usergroup,
                )
                slack.create_usergroup(handle=action.usergroup)

            case SlackUsergroupActionUpdateUsers():
                logger.info(
                    f"Updating users for {action.workspace}/{action.usergroup}: users={action.users}",
                    action_type=action.action_type,
                    workspace=action.workspace,
                    usergroup=action.usergroup,
                    users=action.users,
                )
                slack.update_usergroup_users(
                    handle=action.usergroup, users=action.users
                )

            case SlackUsergroupActionUpdateMetadata():
                logger.info(
                    f"Updating metadata for {action.workspace}/{action.usergroup}: channels={action.channels} description={action.description}",
                    action_type=action.action_type,
                    workspace=action.workspace,
                    usergroup=action.usergroup,
                    channels=action.channels,
                    description=action.description,
                )
                slack.update_usergroup(
                    handle=action.usergroup,
                    channels=action.channels,
                    description=action.description,
                )

    @staticmethod
    def _calculate_update_actions(
        workspace: str,
        current_state: Iterable[SlackUsergroup],
        desired_state: Iterable[SlackUsergroup],
    ) -> list[SlackUsergroupAction]:
        """Compute diff between current and desired state and generate actions.

        Args:
            current_state: List of SlackUsergroupConfig representing current state
            desired_state: List of SlackUsergroupConfig representing desired state
        Returns:
            List of actions to reconcile current state to desired state
        """
        diffs = diff_iterables(current_state, desired_state, key=lambda ug: ug.handle)
        actions: list[SlackUsergroupAction] = [
            SlackUsergroupActionCreate(
                workspace=workspace,
                usergroup=add.handle,
                users=add.config.users,
                description=add.config.description,
            )
            for add in diffs.add.values()
        ]
        # TODO delete usergroup if empty?
        for handle, change in diffs.change.items():
            if change.current.config.users != change.desired.config.users:
                logger.debug(
                    f"Usergroup {handle} users differ. Added: {set(change.desired.config.users) - set(change.current.config.users)}, Removed: {set(change.current.config.users) - set(change.desired.config.users)}"
                )
                actions.append(
                    SlackUsergroupActionUpdateUsers(
                        workspace=workspace,
                        usergroup=handle,
                        users=change.desired.config.users,
                        users_to_add=list(
                            set(change.desired.config.users)
                            - set(change.current.config.users)
                        ),
                        users_to_remove=list(
                            set(change.current.config.users)
                            - set(change.desired.config.users)
                        ),
                    )
                )
            if (
                change.current.config.channels != change.desired.config.channels
                or change.current.config.description
                != change.desired.config.description
            ):
                actions.append(
                    SlackUsergroupActionUpdateMetadata(
                        workspace=workspace,
                        usergroup=handle,
                        description=change.desired.config.description,
                        channels=change.desired.config.channels,
                    )
                )
        return actions

    def reconcile(
        self,
        workspaces: list[SlackWorkspace],
        *,
        dry_run: bool = True,
    ) -> SlackUsergroupsTaskResult:
        """Reconcile Slack usergroups.

        Main reconciliation logic: compare desired state vs current state,
        calculate diff, and execute actions (if dry_run=False).

        Args:
            workspaces: List of Slack workspaces with their usergroups (fully typed!)
            dry_run: If True, only calculate actions without executing (keyword-only)

        Returns:
            ReconcileResponse with actions, applied_count, and errors
        """
        all_actions = []
        errors = []
        applied_count = 0

        # Process each workspace
        for workspace in workspaces:
            logger.info(f"Reconciling workspace: {workspace.name}")
            try:
                slack = self._create_slack_client(workspace.name, workspace.token)
                logger.info(
                    f"Fetching current usergroups for workspace: {workspace.name}"
                )
                current_state = slack.get_slack_usergroups(workspace.managed_usergroups)
                logger.info(
                    f"Cleaning desired usergroups for workspace: {workspace.name}"
                )
                desired_state = slack.clean_slack_usergroups(workspace.usergroups)
                logger.info(f"Calculating actions for workspace: {workspace.name}")
                all_actions.extend(
                    self._calculate_update_actions(
                        workspace=workspace.name,
                        current_state=current_state,
                        desired_state=desired_state,
                    )
                )
            except Exception as e:
                error_msg = f"{workspace.name}: Unexpected error: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)
                continue

            # Execute actions if not dry_run
            if not dry_run and all_actions:
                for action in all_actions:
                    try:
                        self._execute_action(slack=slack, action=action)
                        applied_count += 1
                    except Exception as e:
                        error_msg = f"{action.workspace}/{action.usergroup}: Failed to execute action {action.action_type}: {e}"
                        logger.exception(error_msg)
                        errors.append(error_msg)

        return SlackUsergroupsTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_count=applied_count,
            errors=errors,
        )
