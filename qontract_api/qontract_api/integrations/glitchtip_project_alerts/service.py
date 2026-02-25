"""Glitchtip project alerts reconciliation service."""

import operator

from qontract_utils.differ import diff_iterables
from qontract_utils.glitchtip_api.models import (
    ProjectAlert,
    ProjectAlertRecipient,
    RecipientType,
)

from qontract_api.config import Settings
from qontract_api.integrations.glitchtip_project_alerts.glitchtip_client_factory import (
    GlitchtipClientFactory,
)
from qontract_api.integrations.glitchtip_project_alerts.glitchtip_workspace_client import (
    GlitchtipWorkspaceClient,
)
from qontract_api.integrations.glitchtip_project_alerts.models import (
    GlitchtipAlertActionCreate,
    GlitchtipAlertActionDelete,
    GlitchtipAlertActionUpdate,
    GlitchtipInstance,
    GlitchtipOrganization,
    GlitchtipProjectAlert,
    GlitchtipProjectAlertsTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


def _find_desired_alert(
    desired_orgs: list[GlitchtipOrganization],
    organization: str,
    project: str,
    alert_name: str,
) -> GlitchtipProjectAlert | None:
    """Look up a desired alert by organization, project, and alert name."""
    for org in desired_orgs:
        if org.name != organization:
            continue
        for proj in org.projects:
            if proj.slug != project:
                continue
            for alert in proj.alerts:
                if alert.name == alert_name:
                    return alert
    return None


def _to_api_alert(alert: GlitchtipProjectAlert) -> ProjectAlert:
    """Convert API request model to qontract_utils ProjectAlert.

    Args:
        alert: GlitchtipProjectAlert from API request

    Returns:
        ProjectAlert suitable for qontract_utils glitchtip_api
    """
    return ProjectAlert(
        name=alert.name,
        timespan_minutes=alert.timespan_minutes,
        quantity=alert.quantity,
        recipients=[
            ProjectAlertRecipient(
                recipient_type=RecipientType(r.recipient_type),
                url=r.url,
            )
            for r in alert.recipients
        ],
    )


class GlitchtipProjectAlertsService:
    """Service for reconciling Glitchtip project alerts.

    Handles fetching current state from Glitchtip, computing diffs against desired
    state, and executing reconciliation actions.

    Uses Dependency Injection to keep service decoupled from implementation details.
    """

    def __init__(
        self,
        glitchtip_client_factory: GlitchtipClientFactory,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        """Initialize service.

        Args:
            glitchtip_client_factory: Factory for creating GlitchtipWorkspaceClient instances
            secret_manager: Secret backend for retrieving Glitchtip tokens
            settings: Application settings
        """
        self.glitchtip_client_factory = glitchtip_client_factory
        self.secret_manager = secret_manager
        self.settings = settings

    def _create_glitchtip_client(
        self, instance: GlitchtipInstance
    ) -> GlitchtipWorkspaceClient:
        """Create GlitchtipWorkspaceClient for a given instance.

        Args:
            instance: GlitchtipInstance configuration

        Returns:
            GlitchtipWorkspaceClient with caching + compute layer
        """
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
    ) -> list[
        GlitchtipAlertActionCreate
        | GlitchtipAlertActionUpdate
        | GlitchtipAlertActionDelete
    ]:
        """Calculate reconciliation actions for an instance.

        Fetches current state from Glitchtip and diffs against desired state.

        Args:
            instance_name: Glitchtip instance name (for action metadata)
            glitchtip: GlitchtipWorkspaceClient to fetch current state
            organizations: Desired organizations with project alerts

        Returns:
            List of actions to reconcile current to desired state
        """
        actions: list[
            GlitchtipAlertActionCreate
            | GlitchtipAlertActionUpdate
            | GlitchtipAlertActionDelete
        ] = []

        # Build a map of current projects keyed by org_name/project_slug
        current_orgs = glitchtip.get_organizations()
        current_org_by_name = {org.name: org for org in current_orgs}

        for desired_org in organizations:
            current_org = current_org_by_name.get(desired_org.name)
            if not current_org:
                logger.warning(
                    f"Organization '{desired_org.name}' not found in instance '{instance_name}', skipping"
                )
                continue

            current_projects = glitchtip.get_projects(current_org.slug)
            current_project_by_slug = {p.slug: p for p in current_projects}

            for desired_project in desired_org.projects:
                current_project = current_project_by_slug.get(desired_project.slug)
                if not current_project:
                    logger.warning(
                        f"Project '{desired_project.slug}' not found in org '{desired_org.name}', skipping"
                    )
                    continue

                current_alerts = glitchtip.get_project_alerts(
                    current_org.slug, desired_project.slug
                )

                # Convert desired alerts to qontract_utils models for comparison
                desired_alerts = [_to_api_alert(a) for a in desired_project.alerts]

                diff = diff_iterables(
                    current_alerts,
                    desired_alerts,
                    key=lambda a: a.name,
                    equal=operator.eq,
                )

                actions.extend(
                    GlitchtipAlertActionCreate(
                        instance=instance_name,
                        organization=desired_org.name,
                        project=desired_project.slug,
                        alert_name=alert.name,
                    )
                    for alert in diff.add.values()
                )
                actions.extend(
                    GlitchtipAlertActionUpdate(
                        instance=instance_name,
                        organization=desired_org.name,
                        project=desired_project.slug,
                        alert_name=diff_pair.desired.name,
                    )
                    for diff_pair in diff.change.values()
                )
                actions.extend(
                    GlitchtipAlertActionDelete(
                        instance=instance_name,
                        organization=desired_org.name,
                        project=desired_project.slug,
                        alert_name=alert.name,
                    )
                    for alert in diff.delete.values()
                )

        return actions

    @staticmethod
    def _execute_action(
        glitchtip: GlitchtipWorkspaceClient,
        action: GlitchtipAlertActionCreate
        | GlitchtipAlertActionUpdate
        | GlitchtipAlertActionDelete,
        desired_orgs: list[GlitchtipOrganization],
    ) -> None:
        """Execute a single reconciliation action.

        Args:
            glitchtip: GlitchtipWorkspaceClient
            action: Action to execute
            desired_orgs: Desired organizations (to look up alert details)
        """
        # Find the desired alert from desired_orgs
        desired_alert_model = _find_desired_alert(
            desired_orgs, action.organization, action.project, action.alert_name
        )

        # Find org slug
        current_orgs = glitchtip.get_organizations()
        org_slug = next(
            (o.slug for o in current_orgs if o.name == action.organization),
            action.organization,
        )

        match action:
            case GlitchtipAlertActionCreate():
                logger.info(
                    f"Creating alert: {action.organization}/{action.project}/{action.alert_name}",
                    action_type=action.action_type,
                    instance=action.instance,
                    organization=action.organization,
                    project=action.project,
                    alert_name=action.alert_name,
                )
                if desired_alert_model:
                    glitchtip.create_project_alert(
                        org_slug, action.project, _to_api_alert(desired_alert_model)
                    )

            case GlitchtipAlertActionUpdate():
                logger.info(
                    f"Updating alert: {action.organization}/{action.project}/{action.alert_name}",
                    action_type=action.action_type,
                    instance=action.instance,
                    organization=action.organization,
                    project=action.project,
                    alert_name=action.alert_name,
                )
                if desired_alert_model:
                    # Find current alert pk
                    current_alerts = glitchtip.get_project_alerts(
                        org_slug, action.project
                    )
                    current_alert = next(
                        (a for a in current_alerts if a.name == action.alert_name), None
                    )
                    if current_alert and current_alert.pk is not None:
                        api_alert = _to_api_alert(desired_alert_model)
                        # Set pk for update (model is frozen, rebuild with pk)
                        api_alert_with_pk = api_alert.model_copy(
                            update={"pk": current_alert.pk}
                        )
                        glitchtip.update_project_alert(
                            org_slug, action.project, api_alert_with_pk
                        )

            case GlitchtipAlertActionDelete():
                logger.info(
                    f"Deleting alert: {action.organization}/{action.project}/{action.alert_name}",
                    action_type=action.action_type,
                    instance=action.instance,
                    organization=action.organization,
                    project=action.project,
                    alert_name=action.alert_name,
                )
                current_alerts = glitchtip.get_project_alerts(org_slug, action.project)
                current_alert = next(
                    (a for a in current_alerts if a.name == action.alert_name), None
                )
                if current_alert and current_alert.pk is not None:
                    glitchtip.delete_project_alert(
                        org_slug, action.project, current_alert.pk
                    )

    def reconcile(
        self,
        instances: list[GlitchtipInstance],
        *,
        dry_run: bool = True,
    ) -> GlitchtipProjectAlertsTaskResult:
        """Reconcile Glitchtip project alerts.

        Main reconciliation logic: compare desired state vs current state,
        calculate diff, and execute actions (if dry_run=False).

        Args:
            instances: List of Glitchtip instances to reconcile (organizations embedded)
            dry_run: If True, only calculate actions without executing (keyword-only)

        Returns:
            GlitchtipProjectAlertsTaskResult with actions, applied_count, and errors
        """
        all_actions: list[
            GlitchtipAlertActionCreate
            | GlitchtipAlertActionUpdate
            | GlitchtipAlertActionDelete
        ] = []
        errors: list[str] = []
        applied_count = 0

        for instance in instances:
            instance_desired = instance.organizations
            logger.info(f"Reconciling Glitchtip instance: {instance.name}")

            try:
                glitchtip = self._create_glitchtip_client(instance)
                logger.info(f"Calculating actions for instance: {instance.name}")
                instance_actions = self._calculate_actions(
                    instance_name=instance.name,
                    glitchtip=glitchtip,
                    organizations=instance_desired,
                )
                all_actions.extend(instance_actions)
            except Exception as e:
                error_msg = f"{instance.name}: Unexpected error: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)
                continue

            # Execute actions if not dry_run
            if not dry_run and instance_actions:
                for action in instance_actions:
                    try:
                        self._execute_action(
                            glitchtip=glitchtip,
                            action=action,
                            desired_orgs=instance_desired,
                        )
                        applied_count += 1
                    except Exception as e:
                        error_msg = (
                            f"{action.instance}/{action.organization}/{action.project}"
                            f"/{action.alert_name}: Failed to execute action {action.action_type}: {e}"
                        )
                        logger.exception(error_msg)
                        errors.append(error_msg)

        return GlitchtipProjectAlertsTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_count=applied_count,
            errors=errors,
        )
