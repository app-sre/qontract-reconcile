"""Glitchtip reconciliation service."""

from qontract_utils.glitchtip_api.models import Team as ApiTeam

from qontract_api.config import Settings
from qontract_api.glitchtip import GlitchtipClientFactory, GlitchtipWorkspaceClient
from qontract_api.integrations.glitchtip.domain import (
    GlitchtipInstance,
    GlitchtipOrganization,
    GlitchtipProject,
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
        self, instance: GlitchtipInstance
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
        organizations: list[GlitchtipOrganization],
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
            instance_name: Glitchtip instance name (for logging)
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
                    GlitchtipActionCreateOrganization(organization=desired_org.name)
                )

        # --- Phases 2-4: Per-org reconciliation (only for orgs that currently exist) ---
        for desired_org in organizations:
            current_org = current_org_by_name.get(desired_org.name)
            if not current_org:
                # Org doesn't exist yet — skip current state reads
                continue

            org_slug = current_org.slug
            actions.extend(
                GlitchtipService._calculate_user_actions(
                    desired_org, org_slug, glitchtip, ignore_user_email
                )
            )
            actions.extend(
                GlitchtipService._calculate_team_actions(
                    desired_org, org_slug, glitchtip
                )
            )
            actions.extend(
                GlitchtipService._calculate_project_actions(
                    desired_org, org_slug, glitchtip
                )
            )

        # --- Phase 5: Delete obsolete organizations (last!) ---
        actions.extend(
            GlitchtipActionDeleteOrganization(organization=org_name)
            for org_name in current_org_by_name
            if org_name not in desired_org_names
        )

        return actions

    @staticmethod
    def _calculate_user_actions(
        desired_org: GlitchtipOrganization,
        org_slug: str,
        glitchtip: GlitchtipWorkspaceClient,
        ignore_user_email: str,
    ) -> list[_AnyAction]:
        current_users = glitchtip.get_organization_users(org_slug)
        current_by_email = {
            u.email: u for u in current_users if u.email != ignore_user_email
        }
        desired_by_email = {u.email: u for u in desired_org.users}

        invite_actions: list[_AnyAction] = [
            GlitchtipActionInviteUser(
                organization=desired_org.name,
                email=email,
                role=desired_user.role,
            )
            for email, desired_user in desired_by_email.items()
            if email not in current_by_email
        ]

        delete_actions: list[_AnyAction] = [
            GlitchtipActionDeleteUser(organization=desired_org.name, email=email)
            for email in current_by_email
            if email not in desired_by_email
        ]

        update_actions: list[_AnyAction] = [
            GlitchtipActionUpdateUserRole(
                organization=desired_org.name,
                email=email,
                role=desired_user.role,
            )
            for email, desired_user in desired_by_email.items()
            if (cu := current_by_email.get(email)) and cu.role != desired_user.role
        ]

        return invite_actions + delete_actions + update_actions

    @staticmethod
    def _calculate_team_actions(
        desired_org: GlitchtipOrganization,
        org_slug: str,
        glitchtip: GlitchtipWorkspaceClient,
    ) -> list[_AnyAction]:
        current_teams = glitchtip.get_teams(org_slug)
        current_by_slug = {t.slug: t for t in current_teams}
        desired_by_slug = {_team_slug(dt): dt for dt in desired_org.teams}

        create_actions: list[_AnyAction] = [
            GlitchtipActionCreateTeam(organization=desired_org.name, team_slug=slug)
            for slug in desired_by_slug
            if slug not in current_by_slug
        ]

        delete_actions: list[_AnyAction] = [
            GlitchtipActionDeleteTeam(organization=desired_org.name, team_slug=slug)
            for slug in current_by_slug
            if slug not in desired_by_slug
        ]

        membership_actions: list[_AnyAction] = []
        for slug, desired_team in desired_by_slug.items():
            if slug not in current_by_slug:
                continue  # Team being created — membership seeded during execution
            membership_actions.extend(
                GlitchtipService._calculate_team_membership_actions(
                    desired_org, slug, desired_team, org_slug, glitchtip
                )
            )

        return create_actions + delete_actions + membership_actions

    @staticmethod
    def _calculate_team_membership_actions(
        desired_org: GlitchtipOrganization,
        team_slug: str,
        desired_team: GlitchtipTeam,
        org_slug: str,
        glitchtip: GlitchtipWorkspaceClient,
    ) -> list[_AnyAction]:
        current_team_users = glitchtip.get_team_users(org_slug, team_slug)
        current_emails = {u.email for u in current_team_users}
        desired_emails = {u.email for u in desired_team.users}

        add_actions: list[_AnyAction] = [
            GlitchtipActionAddUserToTeam(
                organization=desired_org.name,
                team_slug=team_slug,
                email=email,
            )
            for email in desired_emails - current_emails
        ]

        remove_actions: list[_AnyAction] = [
            GlitchtipActionRemoveUserFromTeam(
                organization=desired_org.name,
                team_slug=team_slug,
                email=email,
            )
            for email in current_emails - desired_emails
        ]

        return add_actions + remove_actions

    @staticmethod
    def _calculate_project_actions(
        desired_org: GlitchtipOrganization,
        org_slug: str,
        glitchtip: GlitchtipWorkspaceClient,
    ) -> list[_AnyAction]:
        current_projects = glitchtip.get_projects(org_slug)
        current_by_slug = {p.slug: p for p in current_projects}
        desired_by_slug = {p.slug: p for p in desired_org.projects}

        create_actions: list[_AnyAction] = [
            GlitchtipActionCreateProject(
                organization=desired_org.name, project_name=desired_project.name
            )
            for slug, desired_project in desired_by_slug.items()
            if slug not in current_by_slug
        ]

        update_actions: list[_AnyAction] = [
            GlitchtipActionUpdateProject(
                organization=desired_org.name, project_slug=slug
            )
            for slug, desired_project in desired_by_slug.items()
            if (cp := current_by_slug.get(slug))
            and (
                cp.platform != desired_project.platform
                or cp.event_throttle_rate != desired_project.event_throttle_rate
            )
        ]

        delete_actions: list[_AnyAction] = [
            GlitchtipActionDeleteProject(
                organization=desired_org.name, project_slug=slug
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
                    desired_org, slug, desired_project, current_project.team_slugs
                )
            )

        return create_actions + update_actions + delete_actions + team_assoc_actions

    @staticmethod
    def _calculate_project_team_actions(
        desired_org: GlitchtipOrganization,
        project_slug: str,
        desired_project: GlitchtipProject,
        current_team_slugs: list[str],
    ) -> list[_AnyAction]:
        current = set(current_team_slugs)
        desired = set(desired_project.teams)

        add_actions: list[_AnyAction] = [
            GlitchtipActionAddProjectToTeam(
                organization=desired_org.name,
                project_slug=project_slug,
                team_slug=team_slug,
            )
            for team_slug in desired - current
        ]

        remove_actions: list[_AnyAction] = [
            GlitchtipActionRemoveProjectFromTeam(
                organization=desired_org.name,
                project_slug=project_slug,
                team_slug=team_slug,
            )
            for team_slug in current - desired
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
                current_users = glitchtip.get_organization_users(org_slug)
                user = next((u for u in current_users if u.email == action.email), None)
                if user and user.pk is not None:
                    glitchtip.delete_user(org_slug, user.pk)
            case GlitchtipActionUpdateUserRole():
                current_users = glitchtip.get_organization_users(org_slug)
                user = next((u for u in current_users if u.email == action.email), None)
                if user and user.pk is not None:
                    glitchtip.update_user_role(org_slug, user.pk, action.role)

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
                org_users = glitchtip.get_organization_users(org_slug)
                user = next((u for u in org_users if u.email == action.email), None)
                if user and user.pk is not None:
                    glitchtip.add_user_to_team(org_slug, action.team_slug, user.pk)
            case GlitchtipActionRemoveUserFromTeam():
                team_users = glitchtip.get_team_users(org_slug, action.team_slug)
                user = next((u for u in team_users if u.email == action.email), None)
                if user and user.pk is not None:
                    glitchtip.remove_user_from_team(org_slug, action.team_slug, user.pk)

    @staticmethod
    def _execute_project_action(  # noqa: C901
        glitchtip: GlitchtipWorkspaceClient,
        action: GlitchtipActionCreateProject
        | GlitchtipActionUpdateProject
        | GlitchtipActionDeleteProject
        | GlitchtipActionAddProjectToTeam
        | GlitchtipActionRemoveProjectFromTeam,
        org_slug: str,
        desired_org: GlitchtipOrganization | None,
    ) -> None:
        match action:
            case GlitchtipActionCreateProject():
                if desired_org is None:
                    return
                desired_project = next(
                    (p for p in desired_org.projects if p.name == action.project_name),
                    None,
                )
                if desired_project is None:
                    return
                first_team = desired_project.teams[0] if desired_project.teams else None
                if first_team is None:
                    logger.warning(
                        "Cannot create project without a team",
                        project=action.project_name,
                    )
                    return
                new_project = glitchtip.create_project(
                    org_slug, first_team, desired_project.name, desired_project.platform
                )
                if desired_project.event_throttle_rate != 0:
                    glitchtip.update_project(
                        org_slug,
                        new_project.slug,
                        desired_project.name,
                        desired_project.platform,
                        desired_project.event_throttle_rate,
                    )
                for team_slug in desired_project.teams[1:]:
                    glitchtip.add_project_to_team(org_slug, new_project.slug, team_slug)
            case GlitchtipActionUpdateProject():
                if desired_org is None:
                    return
                desired_project = next(
                    (p for p in desired_org.projects if p.slug == action.project_slug),
                    None,
                )
                if desired_project is None:
                    return
                glitchtip.update_project(
                    org_slug,
                    action.project_slug,
                    desired_project.name,
                    desired_project.platform,
                    desired_project.event_throttle_rate,
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
        desired_orgs: list[GlitchtipOrganization],
    ) -> None:
        """Execute a single reconciliation action.

        Args:
            glitchtip: GlitchtipWorkspaceClient
            action: Action to execute
            desired_orgs: Desired organizations (to look up project/team details)
        """
        logger.info(
            "Executing action",
            action_type=action.action_type,
            organization=action.organization,
        )
        current_orgs = glitchtip.get_organizations()
        current_org = current_orgs.get(action.organization)
        org_slug = current_org.slug if current_org else action.organization
        desired_org = next(
            (o for o in desired_orgs if o.name == action.organization), None
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
                GlitchtipService._execute_project_action(
                    glitchtip, action, org_slug, desired_org
                )

    def reconcile(
        self,
        instances: list[GlitchtipInstance],
        *,
        dry_run: bool = True,
    ) -> GlitchtipTaskResult:
        """Reconcile Glitchtip instances (organizations, teams, projects, users).

        Args:
            instances: List of Glitchtip instances with desired state
            dry_run: If True, only calculate actions without executing (keyword-only)

        Returns:
            GlitchtipTaskResult with actions, applied_count, and errors
        """
        all_actions: list[_AnyAction] = []
        errors: list[str] = []
        applied_count = 0

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
                for action in instance_actions:
                    try:
                        self._execute_action(
                            glitchtip=glitchtip,
                            action=action,
                            desired_orgs=instance.organizations,
                        )
                        applied_count += 1
                    except Exception as e:
                        error_msg = (
                            f"{instance.name}/{action.organization}/"
                            f"{action.action_type}: {e}"
                        )
                        logger.exception(error_msg)
                        errors.append(error_msg)

        return GlitchtipTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_count=applied_count,
            errors=errors,
        )
