"""Glitchtip reconciliation service."""

from qontract_utils.glitchtip_api.models import Team as ApiTeam
from qontract_utils.glitchtip_api.models import User as ApiUser

from qontract_api.config import Settings
from qontract_api.glitchtip import GlitchtipClientFactory, GlitchtipWorkspaceClient
from qontract_api.integrations.glitchtip.domain import (
    GIInstance,
    GIOrganization,
    GIProject,
    GlitchtipTeam,
)
from qontract_api.integrations.glitchtip.schemas import (
    GlitchtipActionAddProjectToTeam,
    GlitchtipActionAddUserToTeam,
    GlitchtipActionCreateOrganization,
    GlitchtipActionCreateProject,
    GlitchtipActionCreateTeam,
    GlitchtipActionDeleteOrganization,
    GlitchtipActionDeleteProject,
    GlitchtipActionDeleteTeam,
    GlitchtipActionDeleteUser,
    GlitchtipActionInviteUser,
    GlitchtipActionRemoveProjectFromTeam,
    GlitchtipActionRemoveUserFromTeam,
    GlitchtipActionUpdateProject,
    GlitchtipActionUpdateUserRole,
    GlitchtipTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)

# Type alias for any single action
_AnyAction = (
    GlitchtipActionCreateOrganization
    | GlitchtipActionDeleteOrganization
    | GlitchtipActionInviteUser
    | GlitchtipActionDeleteUser
    | GlitchtipActionUpdateUserRole
    | GlitchtipActionCreateTeam
    | GlitchtipActionDeleteTeam
    | GlitchtipActionAddUserToTeam
    | GlitchtipActionRemoveUserFromTeam
    | GlitchtipActionCreateProject
    | GlitchtipActionUpdateProject
    | GlitchtipActionDeleteProject
    | GlitchtipActionAddProjectToTeam
    | GlitchtipActionRemoveProjectFromTeam
)


def _team_slug(team: GlitchtipTeam) -> str:
    """Derive the Glitchtip slug for a desired team (mirrors Django slugify)."""
    return ApiTeam.model_validate({"name": team.name}).slug


class GlitchtipService:
    """Service for reconciling Glitchtip organizations, teams, projects, and users.

    Follows the three-layer architecture (ADR-014) as Layer 3 (Business Logic).
    Uses Dependency Injection to keep service decoupled from implementation details.

    Reconciliation ordering (preserved from legacy reconciler):
    1. Ensure desired organizations exist (create if missing)
    2. Reconcile users (invite / delete / update_role) — must precede team membership
    3. Reconcile teams (create / delete) — then team membership
    4. Reconcile projects (create / update / delete) — then project-team associations
    5. Delete obsolete organizations last
    """

    def __init__(
        self,
        glitchtip_client_factory: GlitchtipClientFactory,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        self.glitchtip_client_factory = glitchtip_client_factory
        self.secret_manager = secret_manager
        self.settings = settings

    def _create_glitchtip_client(
        self, instance: GIInstance
    ) -> GlitchtipWorkspaceClient:
        token = self.secret_manager.read(instance.token)
        return self.glitchtip_client_factory.create_workspace_client(
            instance_name=instance.name,
            host=instance.console_url,
            token=token,
            read_timeout=instance.read_timeout,
            max_retries=instance.max_retries,
        )

    @staticmethod
    def _calculate_actions(
        instance_name: str,
        glitchtip: GlitchtipWorkspaceClient,
        organizations: list[GIOrganization],
        ignore_user_email: str,
    ) -> list[_AnyAction]:
        """Calculate all reconciliation actions for an instance.

        Follows the reconciliation ordering from the legacy reconciler:
        1. Create missing organizations
        2. User diffs (per org)
        3. Team diffs + team membership diffs (per org)
        4. Project diffs + project-team association diffs (per org)
        5. Delete obsolete organizations

        Args:
            instance_name: Glitchtip instance name (for logging and action context)
            glitchtip: GlitchtipWorkspaceClient to fetch current state
            organizations: Desired organizations
            ignore_user_email: Automation user email to exclude from user diffs

        Returns:
            Ordered list of actions to reconcile current → desired state
        """
        actions: list[_AnyAction] = []
        current_org_by_name = glitchtip.get_organizations()
        desired_org_names = {o.name for o in organizations}

        # --- Phase 1: Ensure desired orgs exist ---
        for desired_org in organizations:
            if desired_org.name not in current_org_by_name:
                logger.info(
                    f"[{instance_name}] Organization '{desired_org.name}' missing — will create"
                )
                actions.append(
                    GlitchtipActionCreateOrganization(
                        instance=instance_name, organization=desired_org.name
                    )
                )
                # Current state is empty by definition — generate all child creates now.
                # This allows single-pass convergence and complete dry-run reporting.
                actions.extend(
                    GlitchtipActionInviteUser(
                        instance=instance_name,
                        organization=desired_org.name,
                        email=user.email,
                        role=user.role,
                    )
                    for user in desired_org.users
                )
                for team in desired_org.teams:
                    team_slug = _team_slug(team)
                    actions.append(
                        GlitchtipActionCreateTeam(
                            instance=instance_name,
                            organization=desired_org.name,
                            team_slug=team_slug,
                        )
                    )
                    actions.extend(
                        GlitchtipActionAddUserToTeam(
                            instance=instance_name,
                            organization=desired_org.name,
                            team_slug=team_slug,
                            email=team_user.email,
                        )
                        for team_user in team.users
                    )
                actions.extend(
                    GlitchtipActionCreateProject(
                        instance=instance_name,
                        organization=desired_org.name,
                        project_name=project.name,
                    )
                    for project in desired_org.projects
                )

        # --- Phases 2-4: Per-org reconciliation (only for orgs that currently exist) ---
        for desired_org in organizations:
            current_org = current_org_by_name.get(desired_org.name)
            if not current_org:
                # New org — child actions already generated in phase 1 above
                continue

            org_slug = current_org.slug
            # Fetch org users once per org — used by both user and team actions to
            # resolve PKs at planning time, avoiding per-action re-fetches at execution.
            current_org_users = glitchtip.get_organization_users(org_slug)
            current_users_by_email: dict[str, ApiUser] = {
                u.email: u for u in current_org_users if u.email != ignore_user_email
            }
            user_actions = GlitchtipService._calculate_user_actions(
                instance_name, desired_org, current_users_by_email
            )
            actions.extend(user_actions)
            users_being_deleted = {
                a.email
                for a in user_actions
                if isinstance(a, GlitchtipActionDeleteUser)
            }
            team_actions = GlitchtipService._calculate_team_actions(
                instance_name,
                desired_org,
                org_slug,
                glitchtip,
                current_users_by_email,
                users_being_deleted=users_being_deleted,
            )
            actions.extend(team_actions)
            teams_being_deleted = {
                a.team_slug
                for a in team_actions
                if isinstance(a, GlitchtipActionDeleteTeam)
            }
            actions.extend(
                GlitchtipService._calculate_project_actions(
                    instance_name,
                    desired_org,
                    org_slug,
                    glitchtip,
                    teams_being_deleted=teams_being_deleted,
                )
            )

        # --- Phase 5: Delete obsolete organizations (last!) ---
        actions.extend(
            GlitchtipActionDeleteOrganization(
                instance=instance_name, organization=org_name
            )
            for org_name in current_org_by_name
            if org_name not in desired_org_names
        )

        return actions

    @staticmethod
    def _calculate_user_actions(
        instance_name: str,
        desired_org: GIOrganization,
        current_users_by_email: dict[str, ApiUser],
    ) -> list[_AnyAction]:
        desired_by_email = {u.email: u for u in desired_org.users}

        invite_actions: list[_AnyAction] = [
            GlitchtipActionInviteUser(
                instance=instance_name,
                organization=desired_org.name,
                email=email,
                role=desired_user.role,
            )
            for email, desired_user in desired_by_email.items()
            if email not in current_users_by_email
        ]

        delete_actions: list[_AnyAction] = [
            GlitchtipActionDeleteUser(
                instance=instance_name,
                organization=desired_org.name,
                email=email,
                pk=current_users_by_email[email].pk,
            )
            for email in current_users_by_email
            if email not in desired_by_email
        ]

        update_actions: list[_AnyAction] = [
            GlitchtipActionUpdateUserRole(
                instance=instance_name,
                organization=desired_org.name,
                email=email,
                role=desired_user.role,
                pk=cu.pk,
            )
            for email, desired_user in desired_by_email.items()
            if (cu := current_users_by_email.get(email))
            and cu.role != desired_user.role
        ]

        return invite_actions + delete_actions + update_actions

    @staticmethod
    def _calculate_team_actions(
        instance_name: str,
        desired_org: GIOrganization,
        org_slug: str,
        glitchtip: GlitchtipWorkspaceClient,
        current_users_by_email: dict[str, ApiUser],
        users_being_deleted: set[str] | None = None,
    ) -> list[_AnyAction]:
        current_teams = glitchtip.get_teams(org_slug)
        current_by_slug = {t.slug: t for t in current_teams}
        desired_by_slug = {_team_slug(dt): dt for dt in desired_org.teams}

        create_actions: list[_AnyAction] = [
            GlitchtipActionCreateTeam(
                instance=instance_name, organization=desired_org.name, team_slug=slug
            )
            for slug in desired_by_slug
            if slug not in current_by_slug
        ]

        delete_actions: list[_AnyAction] = [
            GlitchtipActionDeleteTeam(
                instance=instance_name, organization=desired_org.name, team_slug=slug
            )
            for slug in current_by_slug
            if slug not in desired_by_slug
        ]

        membership_actions: list[_AnyAction] = []
        for slug, desired_team in desired_by_slug.items():
            # For new teams (not yet in current state), pass an empty member list so
            # membership actions are generated immediately — the team will exist by
            # execution time because create_actions run first in the returned list.
            existing_members: list[ApiUser] | None = (
                None if slug in current_by_slug else []
            )
            membership_actions.extend(
                GlitchtipService._calculate_team_membership_actions(
                    instance_name,
                    desired_org,
                    slug,
                    desired_team,
                    org_slug,
                    glitchtip,
                    current_users_by_email,
                    users_being_deleted=users_being_deleted or set(),
                    current_team_users=existing_members,
                )
            )

        return create_actions + delete_actions + membership_actions

    @staticmethod
    def _calculate_team_membership_actions(
        instance_name: str,
        desired_org: GIOrganization,
        team_slug: str,
        desired_team: GlitchtipTeam,
        org_slug: str,
        glitchtip: GlitchtipWorkspaceClient,
        current_users_by_email: dict[str, ApiUser],
        users_being_deleted: set[str] | None = None,
        current_team_users: list[ApiUser] | None = None,
    ) -> list[_AnyAction]:
        if current_team_users is None:
            current_team_users = glitchtip.get_team_users(org_slug, team_slug)
        current_emails = {u.email for u in current_team_users}
        current_team_by_email = {u.email: u for u in current_team_users}
        desired_emails = {u.email for u in desired_team.users}
        deleted_users = users_being_deleted or set()

        add_actions: list[_AnyAction] = [
            GlitchtipActionAddUserToTeam(
                instance=instance_name,
                organization=desired_org.name,
                team_slug=team_slug,
                email=email,
                # pk is known for existing org members; None for users being invited
                # in the same reconcile run (pk resolved at execution time)
                pk=current_users_by_email[email].pk
                if email in current_users_by_email
                else None,
            )
            for email in desired_emails - current_emails
        ]

        remove_actions: list[_AnyAction] = [
            GlitchtipActionRemoveUserFromTeam(
                instance=instance_name,
                organization=desired_org.name,
                team_slug=team_slug,
                email=email,
                pk=current_team_by_email[email].pk,
            )
            for email in current_emails - desired_emails
            if email not in deleted_users
        ]

        return add_actions + remove_actions

    @staticmethod
    def _calculate_project_actions(
        instance_name: str,
        desired_org: GIOrganization,
        org_slug: str,
        glitchtip: GlitchtipWorkspaceClient,
        teams_being_deleted: set[str] | None = None,
    ) -> list[_AnyAction]:
        current_projects = glitchtip.get_projects(org_slug)
        current_by_slug = {p.slug: p for p in current_projects}
        desired_by_slug = {p.slug: p for p in desired_org.projects}

        create_actions: list[_AnyAction] = [
            GlitchtipActionCreateProject(
                instance=instance_name,
                organization=desired_org.name,
                project_name=desired_project.name,
                platform=desired_project.platform,
                event_throttle_rate=desired_project.event_throttle_rate,
                teams=desired_project.teams,
            )
            for slug, desired_project in desired_by_slug.items()
            if slug not in current_by_slug
        ]

        update_actions: list[_AnyAction] = [
            GlitchtipActionUpdateProject(
                instance=instance_name,
                organization=desired_org.name,
                project_slug=slug,
                name=desired_project.name,
                platform=desired_project.platform,
                event_throttle_rate=desired_project.event_throttle_rate,
            )
            for slug, desired_project in desired_by_slug.items()
            if (cp := current_by_slug.get(slug))
            and (
                cp.name != desired_project.name
                or cp.platform != desired_project.platform
                or cp.event_throttle_rate != desired_project.event_throttle_rate
            )
        ]

        delete_actions: list[_AnyAction] = [
            GlitchtipActionDeleteProject(
                instance=instance_name,
                organization=desired_org.name,
                project_slug=slug,
            )
            for slug in current_by_slug
            if slug not in desired_by_slug
        ]

        team_assoc_actions: list[_AnyAction] = []
        for slug, desired_project in desired_by_slug.items():
            current_project = current_by_slug.get(slug)
            if current_project is None:
                continue  # Being created — associations handled during execution
            team_assoc_actions.extend(
                GlitchtipService._calculate_project_team_actions(
                    instance_name,
                    desired_org,
                    slug,
                    desired_project,
                    current_project.team_slugs,
                    teams_being_deleted=teams_being_deleted or set(),
                )
            )

        return create_actions + update_actions + delete_actions + team_assoc_actions

    @staticmethod
    def _calculate_project_team_actions(
        instance_name: str,
        desired_org: GIOrganization,
        project_slug: str,
        desired_project: GIProject,
        current_team_slugs: list[str],
        teams_being_deleted: set[str] | None = None,
    ) -> list[_AnyAction]:
        current = set(current_team_slugs)
        desired = set(desired_project.teams)
        deleted_teams = teams_being_deleted or set()

        add_actions: list[_AnyAction] = [
            GlitchtipActionAddProjectToTeam(
                instance=instance_name,
                organization=desired_org.name,
                project_slug=project_slug,
                team_slug=team_slug,
            )
            for team_slug in desired - current
        ]

        remove_actions: list[_AnyAction] = [
            GlitchtipActionRemoveProjectFromTeam(
                instance=instance_name,
                organization=desired_org.name,
                project_slug=project_slug,
                team_slug=team_slug,
            )
            for team_slug in current - desired
            if team_slug not in deleted_teams
        ]

        return add_actions + remove_actions

    @staticmethod
    def _execute_org_action(
        glitchtip: GlitchtipWorkspaceClient,
        action: GlitchtipActionCreateOrganization | GlitchtipActionDeleteOrganization,
        org_slug: str,
    ) -> None:
        match action:
            case GlitchtipActionCreateOrganization():
                glitchtip.create_organization(action.organization)
            case GlitchtipActionDeleteOrganization():
                glitchtip.delete_organization(org_slug)

    @staticmethod
    def _execute_user_action(
        glitchtip: GlitchtipWorkspaceClient,
        action: GlitchtipActionInviteUser
        | GlitchtipActionDeleteUser
        | GlitchtipActionUpdateUserRole,
        org_slug: str,
    ) -> None:
        match action:
            case GlitchtipActionInviteUser():
                glitchtip.invite_user(org_slug, action.email, action.role)
            case GlitchtipActionDeleteUser():
                glitchtip.delete_user(org_slug, action.pk)
            case GlitchtipActionUpdateUserRole():
                glitchtip.update_user_role(org_slug, action.pk, action.role)

    @staticmethod
    def _execute_team_action(
        glitchtip: GlitchtipWorkspaceClient,
        action: GlitchtipActionCreateTeam
        | GlitchtipActionDeleteTeam
        | GlitchtipActionAddUserToTeam
        | GlitchtipActionRemoveUserFromTeam,
        org_slug: str,
    ) -> None:
        match action:
            case GlitchtipActionCreateTeam():
                glitchtip.create_team(org_slug, action.team_slug)
            case GlitchtipActionDeleteTeam():
                glitchtip.delete_team(org_slug, action.team_slug)
            case GlitchtipActionAddUserToTeam():
                pk = action.pk
                if pk is None:
                    # User was invited in the same reconcile run — pk not known at
                    # planning time, resolve it now after invite has been executed.
                    org_users = glitchtip.get_organization_users(org_slug)
                    user = next((u for u in org_users if u.email == action.email), None)
                    pk = user.pk if user else None
                if pk is None:
                    raise RuntimeError(
                        f"Cannot add {action.email} to team {action.team_slug}: "
                        "user not found in organization (invite may have failed)"
                    )
                glitchtip.add_user_to_team(org_slug, action.team_slug, pk)
            case GlitchtipActionRemoveUserFromTeam():
                glitchtip.remove_user_from_team(org_slug, action.team_slug, action.pk)

    @staticmethod
    def _execute_project_action(
        glitchtip: GlitchtipWorkspaceClient,
        action: GlitchtipActionCreateProject
        | GlitchtipActionUpdateProject
        | GlitchtipActionDeleteProject
        | GlitchtipActionAddProjectToTeam
        | GlitchtipActionRemoveProjectFromTeam,
        org_slug: str,
    ) -> None:
        match action:
            case GlitchtipActionCreateProject():
                if not action.teams:
                    logger.warning(
                        "Cannot create project without a team",
                        project=action.project_name,
                    )
                    return
                new_project = glitchtip.create_project(
                    org_slug, action.teams[0], action.project_name, action.platform
                )
                if action.event_throttle_rate != 0:
                    glitchtip.update_project(
                        org_slug,
                        new_project.slug,
                        action.project_name,
                        action.platform,
                        action.event_throttle_rate,
                    )
                for team_slug in action.teams[1:]:
                    glitchtip.add_project_to_team(org_slug, new_project.slug, team_slug)
            case GlitchtipActionUpdateProject():
                glitchtip.update_project(
                    org_slug,
                    action.project_slug,
                    action.name,
                    action.platform,
                    action.event_throttle_rate,
                )
            case GlitchtipActionDeleteProject():
                glitchtip.delete_project(org_slug, action.project_slug)
            case GlitchtipActionAddProjectToTeam():
                glitchtip.add_project_to_team(
                    org_slug, action.project_slug, action.team_slug
                )
            case GlitchtipActionRemoveProjectFromTeam():
                glitchtip.remove_project_from_team(
                    org_slug, action.project_slug, action.team_slug
                )

    @staticmethod
    def _execute_action(
        glitchtip: GlitchtipWorkspaceClient,
        action: _AnyAction,
        org_slug: str,
    ) -> None:
        """Execute a single reconciliation action.

        Args:
            glitchtip: GlitchtipWorkspaceClient
            action: Action to execute
            org_slug: Current slug for action.organization (pre-fetched by caller)
        """
        logger.info(
            "Executing action",
            action_type=action.action_type,
            organization=action.organization,
        )

        match action:
            case (
                GlitchtipActionCreateOrganization()
                | GlitchtipActionDeleteOrganization()
            ):
                GlitchtipService._execute_org_action(glitchtip, action, org_slug)
            case (
                GlitchtipActionInviteUser()
                | GlitchtipActionDeleteUser()
                | GlitchtipActionUpdateUserRole()
            ):
                GlitchtipService._execute_user_action(glitchtip, action, org_slug)
            case (
                GlitchtipActionCreateTeam()
                | GlitchtipActionDeleteTeam()
                | GlitchtipActionAddUserToTeam()
                | GlitchtipActionRemoveUserFromTeam()
            ):
                GlitchtipService._execute_team_action(glitchtip, action, org_slug)
            case (
                GlitchtipActionCreateProject()
                | GlitchtipActionUpdateProject()
                | GlitchtipActionDeleteProject()
                | GlitchtipActionAddProjectToTeam()
                | GlitchtipActionRemoveProjectFromTeam()
            ):
                GlitchtipService._execute_project_action(glitchtip, action, org_slug)

    def reconcile(
        self,
        instances: list[GIInstance],
        *,
        dry_run: bool = True,
    ) -> GlitchtipTaskResult:
        """Reconcile Glitchtip instances (organizations, teams, projects, users).

        Args:
            instances: List of Glitchtip instances with desired state
            dry_run: If True, only calculate actions without executing (keyword-only)

        Returns:
            GlitchtipTaskResult with actions, applied_actions, applied_count, and errors
        """
        all_actions: list[_AnyAction] = []
        applied_actions: list[_AnyAction] = []
        errors: list[str] = []

        for instance in instances:
            logger.info(f"Reconciling Glitchtip instance: {instance.name}")

            try:
                ignore_email = self.secret_manager.read(instance.automation_user_email)
                glitchtip = self._create_glitchtip_client(instance)
                instance_actions = self._calculate_actions(
                    instance_name=instance.name,
                    glitchtip=glitchtip,
                    organizations=instance.organizations,
                    ignore_user_email=ignore_email,
                )
                all_actions.extend(instance_actions)
            except Exception as e:
                error_msg = f"{instance.name}: Unexpected error: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)
                continue

            if not dry_run:
                current_orgs = glitchtip.get_organizations()
                for action in instance_actions:
                    current_org = current_orgs.get(action.organization)
                    org_slug = current_org.slug if current_org else action.organization
                    try:
                        self._execute_action(
                            glitchtip=glitchtip,
                            action=action,
                            org_slug=org_slug,
                        )
                        applied_actions.append(action)
                    except Exception as e:
                        error_msg = (
                            f"{instance.name}/{action.organization}/"
                            f"{action.action_type}: {e}"
                        )
                        logger.exception(error_msg)
                        errors.append(error_msg)
                    if isinstance(
                        action,
                        GlitchtipActionCreateOrganization
                        | GlitchtipActionDeleteOrganization,
                    ):
                        current_orgs = glitchtip.get_organizations()

        return GlitchtipTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
