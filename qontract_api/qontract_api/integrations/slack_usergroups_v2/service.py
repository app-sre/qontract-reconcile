"""Slack usergroups reconciliation service."""

from collections.abc import Iterable

from qontract_utils.differ import diff_iterables
from qontract_utils.secret_reader.base import SecretBackend

from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups_v2.models import (
    SlackUsergroup,
    SlackUsergroupAction,
    SlackUsergroupActionCreate,
    SlackUsergroupActionUpdateMetadata,
    SlackUsergroupActionUpdateUsers,
    SlackUsergroupRequest,
    SlackUsergroupsReconcilePayload,
    SlackUsergroupsTaskResult,
    UserSourceGitOwners,
    UserSourceOrgUsernames,
    UserSourcePagerDuty,
)
from qontract_api.integrations.slack_usergroups_v2.slack_client_factory import (
    SlackClientFactory,
)
from qontract_api.integrations.slack_usergroups_v2.slack_workspace_client import (
    SlackWorkspaceClient,
)
from qontract_api.integrations.slack_usergroups_v2.user_source_git_owners_resolver import (
    UserSourceGitOwnersResolver,
)
from qontract_api.integrations.slack_usergroups_v2.user_source_org_usernames_resolver import (
    UserSourceOrgUsernamesResolver,
)
from qontract_api.integrations.slack_usergroups_v2.user_source_pager_duty_schedule_resolver import (
    UserSourcePagerDutyResolver,
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
        slack_client_factory: SlackClientFactory,
        secret_reader: SecretBackend,
        settings: Settings,
        user_source_git_owners_resolver: UserSourceGitOwnersResolver,
        user_source_org_usernames_resolver: UserSourceOrgUsernamesResolver,
        user_source_pagerduty_resolver: UserSourcePagerDutyResolver,
    ) -> None:
        """Initialize service.

        Args:
            slack_client_factory: Factory for creating SlackWorkspaceClient instances
            secret_reader: Secret backend for retrieving Slack tokens
            settings: Application settings
            user_source_git_owners_resolver: Resolver for Git Owners user sources
            user_source_org_usernames_resolver: Resolver for Org Usernames user sources
            user_source_pagerduty_resolver: Resolver for PagerDuty user sources
        """
        self.slack_client_factory = slack_client_factory
        self.secret_reader = secret_reader
        self.settings = settings
        self.user_source_git_owners_resolver = user_source_git_owners_resolver
        self.user_source_org_usernames_resolver = user_source_org_usernames_resolver
        self.user_source_pagerduty_resolver = user_source_pagerduty_resolver

    def _create_slack_client(self, workspace_name: str) -> SlackWorkspaceClient:
        """Create SlackWorkspaceClient with caching, locking, and rate limiting.

        Fetches token from secret backend and uses factory to create client.

        Args:
            workspace_name: Name of the Slack workspace

        Returns:
            SlackWorkspaceClient instance with full caching + compute layer
        """
        token = self.secret_reader.read(
            self.settings.slack.workspaces[workspace_name]
            .integrations["slack-usergroups"]
            .token
        )

        # Use factory to create client
        return self.slack_client_factory.create_workspace_client(
            workspace_name=workspace_name,
            token=token,
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
                users=add.users,
                description=add.description,
            )
            for add in diffs.add.values()
        ]
        # TODO delete usergroup if empty?
        for handle, change in diffs.change.items():
            if change.current.users != change.desired.users:
                logger.debug(
                    f"Usergroup {handle} users differ. Added: {set(change.desired.users) - set(change.current.users)}, Removed: {set(change.current.users) - set(change.desired.users)}"
                )
                actions.append(
                    SlackUsergroupActionUpdateUsers(
                        workspace=workspace,
                        usergroup=handle,
                        users=change.desired.users,
                        users_to_add=list(
                            set(change.desired.users) - set(change.current.users)
                        ),
                        users_to_remove=list(
                            set(change.current.users) - set(change.desired.users)
                        ),
                    )
                )
            if (
                change.current.channels != change.desired.channels
                or change.current.description != change.desired.description
            ):
                actions.append(
                    SlackUsergroupActionUpdateMetadata(
                        workspace=workspace,
                        usergroup=handle,
                        description=change.desired.description,
                        channels=change.desired.channels,
                    )
                )
        return actions

    def resolve_users_from_source(
        self,
        source: UserSourceOrgUsernames | UserSourceGitOwners | UserSourcePagerDuty,
    ) -> set[str]:
        # TODO: extract to UserSourceFactory if more sources are needed
        match source.provider:
            case "org_username":
                return self.user_source_org_usernames_resolver.resolve(
                    source.org_usernames
                )
            case "git_owners":
                return self.user_source_git_owners_resolver.resolve(source.git_url)
            case "pagerduty":
                return self.user_source_pagerduty_resolver.resolve(
                    instance_name=source.instance_name,
                    schedule_id=source.schedule_id,
                    escalation_policy_id=source.escalation_policy_id,
                )
            case _:
                raise ValueError(f"Unsupported user source provider: {source.provider}")

    def build_desired_usergroup(
        self, usergroup: SlackUsergroupRequest
    ) -> SlackUsergroup:
        resolved_users = [
            self.resolve_users_from_source(user_source)
            for user_source in usergroup.user_sources
        ]
        users = sorted(set().union(*resolved_users))
        return SlackUsergroup(
            handle=usergroup.handle,
            description=usergroup.description,
            users=users,
            channels=sorted(usergroup.channels),
        )

    def build_desired_usergroups(
        self,
        usergroups: list[SlackUsergroupRequest],
    ) -> list[SlackUsergroup]:
        return [self.build_desired_usergroup(ug) for ug in usergroups]

    def reconcile(
        self,
        payload: SlackUsergroupsReconcilePayload,
        *,
        dry_run: bool = True,
    ) -> SlackUsergroupsTaskResult:
        """Reconcile Slack usergroups.

        Main reconciliation logic: compare desired state vs current state,
        calculate diff, and execute actions (if dry_run=False).

        Args:
            payload: Reconciliation payload with workspaces and users
            dry_run: If True, only calculate actions without executing (keyword-only)

        Returns:
            ReconcileResponse with actions, applied_count, and errors
        """
        all_actions = []
        errors = []
        applied_count = 0

        # Process each workspace
        for workspace in payload.workspaces:
            try:
                slack = self._create_slack_client(workspace.name)
                current_state = slack.get_slack_usergroups(workspace.managed_usergroups)
                desired_state = slack.clean_slack_usergroups(
                    self.build_desired_usergroups(workspace.usergroups)
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
