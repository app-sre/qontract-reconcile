"""Slack usergroups reconciliation service."""

from collections.abc import Callable, Iterable

from qontract_utils.differ import diff_iterables

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroup,
    SlackUsergroupAction,
    SlackUsergroupActionCreate,
    SlackUsergroupActionUpdateMetadata,
    SlackUsergroupActionUpdateUsers,
    SlackUsergroupConfig,
    SlackUsergroupsTaskResult,
    SlackWorkspace,
)
from qontract_api.integrations.slack_usergroups.slack_workspace_client import (
    SlackWorkspaceClient,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

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
        settings: Settings,
        get_slack_token: Callable[[str], str],
        create_slack_client: Callable[
            [str, str, CacheBackend, Settings], SlackWorkspaceClient
        ],
    ) -> None:
        """Initialize service.

        Args:
            cache: Cache backend for storing current state
            settings: Application settings
            get_slack_token: Function to retrieve Slack token from vault path.
                           Injected dependency - implementation provided by caller.
                           Signature: (vault_path: str) -> token: str
            create_slack_client: Factory function to create SlackWorkspaceClient.
                                Injected dependency - implementation provided by caller.
                                Signature: (workspace_name, token, cache, settings) -> SlackWorkspaceClient
        """
        self.cache = cache
        self.settings = settings
        self.get_slack_token = get_slack_token
        self.create_slack_client = create_slack_client

    def _create_slack_client(
        self, workspace_name: str, vault_token_path: str
    ) -> SlackWorkspaceClient:
        """Create SlackWorkspaceClient with caching, locking, and rate limiting.

        Uses injected factory function to create client (Dependency Injection).
        Works in both FastAPI (async) and Celery (sync) contexts.

        Args:
            workspace_name: Slack workspace name
            vault_token_path: Vault path to Slack token

        Returns:
            SlackWorkspaceClient instance (Layer 2 - Cache + Compute)
        """
        token = self.get_slack_token(vault_token_path)
        return self.create_slack_client(
            workspace_name,
            token,
            self.cache,
            self.settings,
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
            # TODO delete Usergroup action
            case SlackUsergroupActionCreate():
                logger.info(
                    f"Creating usergroup: {action.workspace}/{action.usergroup}",
                    extra={
                        "action_type": action.action_type,
                        "workspace": action.workspace,
                        "usergroup": action.usergroup,
                    },
                )
                slack.create_usergroup(handle=action.usergroup)

            case SlackUsergroupActionUpdateUsers():
                logger.info(
                    f"Updating users for {action.workspace}/{action.usergroup}: users={action.users}",
                    extra={
                        "action_type": action.action_type,
                        "workspace": action.workspace,
                        "usergroup": action.usergroup,
                        "users": action.users,
                    },
                )
                slack.update_usergroup_users(
                    handle=action.usergroup, users=action.users
                )

            case SlackUsergroupActionUpdateMetadata():
                logger.info(
                    f"Updating metadata for {action.workspace}/{action.usergroup}: channels={action.channels} description={action.description}",
                    extra={
                        "action_type": action.action_type,
                        "workspace": action.workspace,
                        "usergroup": action.usergroup,
                        "channels": action.channels,
                        "description": action.description,
                    },
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
        # TODO handle usergroup deletion
        for handle, change in diffs.change.items():
            if change.current.config.users != change.desired.config.users:
                actions.append(
                    SlackUsergroupActionUpdateUsers(
                        workspace=workspace,
                        usergroup=handle,
                        users=change.desired.config.users,
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

    @staticmethod
    def _fetch_current_state(
        slack: SlackWorkspaceClient, managed_usergroups: list[str]
    ) -> list[SlackUsergroup]:
        """Fetch current state from Slack.

        Returns:
            List of SlackUsergroupConfig representing current state
        """
        current_state: list[SlackUsergroup] = []

        for managed_usergroup in managed_usergroups:
            if ug := slack.get_usergroup_by_handle(managed_usergroup):
                description = ug.description
                users = [user.org_username for user in slack.get_users_by_ids(ug.users)]
                channels = [
                    channel.name
                    for channel in slack.get_channels_by_ids(ug.prefs.channels)
                ]

                current_state.append(
                    SlackUsergroup(
                        handle=managed_usergroup,
                        config=SlackUsergroupConfig(
                            description=description, users=users, channels=channels
                        ),
                    )
                )
        return current_state

    @staticmethod
    def _clean_up_usergroups(
        slack: SlackWorkspaceClient,
        usergroups: Iterable[SlackUsergroup],
    ) -> list[SlackUsergroup]:
        """Clean up desired usergroups by removing non-existing users/channels.

        Args:
            slack: SlackWorkspaceClient
            usergroups: List of desired SlackUsergroup configurations

        Returns:
            List of cleaned SlackUsergroup configurations
        """
        return [
            SlackUsergroup(
                handle=ug.handle,
                config=SlackUsergroupConfig(
                    description=ug.config.description,
                    users=[
                        u.org_username
                        for u in slack.get_users_by_org_names(ug.config.users)
                    ],
                    channels=[
                        c.name for c in slack.get_channels_by_names(ug.config.channels)
                    ],
                ),
            )
            for ug in usergroups
        ]

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
            try:
                slack = self._create_slack_client(
                    workspace.name, workspace.vault_token_path
                )
                current_state = self._fetch_current_state(
                    slack=slack, managed_usergroups=workspace.managed_usergroups
                )
                desired_state = self._clean_up_usergroups(
                    slack=slack, usergroups=workspace.usergroups
                )
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
            errors=errors or None,
        )
