import logging
import sys
from collections import defaultdict
from collections.abc import (
    Callable,
    Iterable,
)
from urllib.parse import urlencode

from qontract_api_client.api.integrations.glitchtip_project_alerts import (
    GlitchtipProjectAlertsTaskResponse,
)
from qontract_api_client.api.integrations.glitchtip_project_alerts import (
    asyncio as reconcile_glitchtip_project_alerts,
)
from qontract_api_client.api.integrations.glitchtip_project_alerts_task_status import (
    asyncio as glitchtip_project_alerts_task_status,
)
from qontract_api_client.models.glitchtip_instance import (
    GlitchtipInstance as GlitchtipInstanceRequest,
)
from qontract_api_client.models.glitchtip_organization import (
    GlitchtipOrganization as GlitchtipOrganizationRequest,
)
from qontract_api_client.models.glitchtip_project import (
    GlitchtipProject as GlitchtipProjectRequest,
)
from qontract_api_client.models.glitchtip_project_alert import (
    GlitchtipProjectAlert as GlitchtipProjectAlertRequest,
)
from qontract_api_client.models.glitchtip_project_alert_recipient import (
    GlitchtipProjectAlertRecipient as GlitchtipProjectAlertRecipientRequest,
)
from qontract_api_client.models.glitchtip_project_alerts_reconcile_request import (
    GlitchtipProjectAlertsReconcileRequest,
)
from qontract_api_client.models.secret import Secret
from qontract_api_client.models.task_status import TaskStatus

from reconcile import jira_permissions_validator
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    GlitchtipInstanceV1,
)
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    query as glitchtip_instance_query,
)
from reconcile.gql_definitions.glitchtip_project_alerts.glitchtip_project import (
    GlitchtipProjectAlertRecipientEmailV1,
    GlitchtipProjectAlertRecipientV1,
    GlitchtipProjectAlertRecipientWebhookV1,
    GlitchtipProjectJiraV1,
    GlitchtipProjectV1,
)
from reconcile.gql_definitions.glitchtip_project_alerts.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.glitchtip.models import (
    Organization,
    Project,
    ProjectAlert,
    ProjectAlertRecipient,
    RecipientType,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

QONTRACT_INTEGRATION = "glitchtip-project-alerts-api"
GJB_ALERT_NAME = "Glitchtip-Jira-Bridge-Integration"


class GlitchtipProjectAlertsIntegrationParams(PydanticRunParams):
    instance: str | None = None


def webhook_urls_are_unique(alerts: Iterable[ProjectAlert]) -> bool:
    """Check that webhook URLs are unique across a project."""
    urls = []
    for alert in alerts:
        for recipient in alert.recipients:
            if recipient.recipient_type == RecipientType.WEBHOOK:
                if recipient.url in urls:
                    return False
                urls.append(recipient.url)
    return True


class GlitchtipProjectAlertsIntegration(
    QontractReconcileApiIntegration[GlitchtipProjectAlertsIntegrationParams]
):
    """Manage Glitchtip project alerts."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_projects(self, query_func: Callable) -> list[GlitchtipProjectV1]:
        return glitchtip_project_query(query_func=query_func).glitchtip_projects or []

    def _build_project_alert_recipient(
        self,
        recipient: GlitchtipProjectAlertRecipientEmailV1
        | GlitchtipProjectAlertRecipientWebhookV1
        | GlitchtipProjectAlertRecipientV1,
    ) -> ProjectAlertRecipient:
        if isinstance(recipient, GlitchtipProjectAlertRecipientEmailV1):
            return ProjectAlertRecipient(recipient_type=RecipientType.EMAIL)
        if isinstance(recipient, GlitchtipProjectAlertRecipientWebhookV1):
            url = recipient.url
            if not url and recipient.url_secret:
                url = self.secret_reader.read_secret(recipient.url_secret)
            if not url:
                raise ValueError("url or urlSecret must be set for webhook recipient")
            return ProjectAlertRecipient(recipient_type=RecipientType.WEBHOOK, url=url)
        raise TypeError("Unsupported type")

    def _build_jira_project_alert(
        self,
        gjb_alert_url: str,
        gjb_token: str | None,
        jira: GlitchtipProjectJiraV1,
    ) -> ProjectAlert:
        token_params = {"token": gjb_token} if gjb_token else {}
        params: dict[str, str | list[str]] = {
            "labels": jira.labels or [],
            "components": jira.components or [],
        } | token_params
        url = f"{gjb_alert_url}/{jira.project}?{urlencode(params, True)}"
        return ProjectAlert(
            name=GJB_ALERT_NAME,
            timespan_minutes=1,
            quantity=1,
            recipients=[
                ProjectAlertRecipient(recipient_type=RecipientType.WEBHOOK, url=url)
            ],
        )

    def _build_jira_escalation_alerts(
        self,
        gjb_alert_url: str,
        gjb_token: str | None,
        jira: GlitchtipProjectJiraV1,
    ) -> list[ProjectAlert]:
        assert jira.escalation_policy is not None
        token_params = {"token": gjb_token} if gjb_token else {}
        channels = jira.escalation_policy.channels
        alerts = []
        for board in channels.jira_board:
            if not integration_is_enabled(
                QONTRACT_INTEGRATION, board
            ) or not integration_is_enabled(
                jira_permissions_validator.QONTRACT_INTEGRATION, board
            ):
                continue
            params: dict[str, str | list[str]] = {
                "labels": (jira.labels or []) + (channels.jira_labels or []),
                "components": channels.jira_components or [],
            } | token_params
            if board.issue_type:
                params["issue_type"] = board.issue_type
            url = f"{gjb_alert_url}/{board.name}?{urlencode(params, True)}"
            alerts.append(
                ProjectAlert(
                    name=GJB_ALERT_NAME,
                    timespan_minutes=1,
                    quantity=1,
                    recipients=[
                        ProjectAlertRecipient(
                            recipient_type=RecipientType.WEBHOOK, url=url
                        )
                    ],
                )
            )
        return alerts

    def _build_jira_alerts(
        self,
        glitchtip_project: GlitchtipProjectV1,
        gjb_alert_url: str | None,
        gjb_token: str | None,
    ) -> list[ProjectAlert]:
        if not (glitchtip_project.jira and gjb_alert_url):
            return []
        jira = glitchtip_project.jira
        if jira.project:
            return [self._build_jira_project_alert(gjb_alert_url, gjb_token, jira)]
        if jira.escalation_policy and jira.escalation_policy.channels.jira_board:
            return self._build_jira_escalation_alerts(gjb_alert_url, gjb_token, jira)
        raise ValueError(
            "Jira integration requires either project or escalation policy to be set"
        )

    def _build_project(
        self,
        glitchtip_project: GlitchtipProjectV1,
        gjb_alert_url: str | None,
        gjb_token: str | None,
    ) -> Project:
        alerts = []
        for alert in glitchtip_project.alerts or []:
            if alert.name == GJB_ALERT_NAME:
                raise ValueError(
                    f"'{GJB_ALERT_NAME}' alert name is reserved. Please use another name."
                )
            alerts.append(
                ProjectAlert(
                    name=alert.name,
                    timespan_minutes=alert.timespan_minutes,
                    quantity=alert.quantity,
                    recipients=[
                        self._build_project_alert_recipient(recp)
                        for recp in alert.recipients
                    ],
                )
            )
        alerts.extend(
            self._build_jira_alerts(glitchtip_project, gjb_alert_url, gjb_token)
        )

        if not webhook_urls_are_unique(alerts):
            raise ValueError(
                "Glitchtip project alert webhook URLs must be unique across a project. Do not trigger the same webhook twice."
            )

        return Project(
            name=glitchtip_project.name,
            platform=None,
            slug=glitchtip_project.project_id or "",
            alerts=alerts,
        )

    def fetch_desired_state(
        self,
        glitchtip_projects: Iterable[GlitchtipProjectV1],
        gjb_alert_url: str | None,
        gjb_token: str | None,
    ) -> list[Organization]:
        organizations: dict[str, Organization] = {}
        for glitchtip_project in glitchtip_projects:
            organization = organizations.setdefault(
                glitchtip_project.organization.name,
                Organization(name=glitchtip_project.organization.name),
            )
            organization.projects.append(
                self._build_project(glitchtip_project, gjb_alert_url, gjb_token)
            )
        return list(organizations.values())

    @staticmethod
    def _build_api_desired_state(
        orgs: list[Organization],
    ) -> list[GlitchtipOrganizationRequest]:
        return [
            GlitchtipOrganizationRequest(
                name=org.name,
                projects=[
                    GlitchtipProjectRequest(
                        name=proj.name,
                        slug=proj.slug,
                        alerts=[
                            GlitchtipProjectAlertRequest(
                                name=alert.name,
                                timespan_minutes=alert.timespan_minutes,
                                quantity=alert.quantity,
                                recipients=[
                                    GlitchtipProjectAlertRecipientRequest(
                                        recipient_type=r.recipient_type.value,
                                        url=r.url,
                                    )
                                    for r in alert.recipients
                                ],
                            )
                            for alert in proj.alerts
                        ],
                    )
                    for proj in org.projects
                ],
            )
            for org in orgs
        ]

    async def reconcile(
        self,
        instances: list[GlitchtipInstanceV1],
        desired_state: dict[str, list[Organization]],
        dry_run: bool,
    ) -> GlitchtipProjectAlertsTaskResponse:
        request_data = GlitchtipProjectAlertsReconcileRequest(
            instances=[
                GlitchtipInstanceRequest(
                    name=gi.name,
                    console_url=gi.console_url,
                    token=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=gi.automation_token.path,
                        field=gi.automation_token.field,
                        version=gi.automation_token.version,
                    ),
                    read_timeout=gi.read_timeout or 30,
                    max_retries=gi.max_retries or 3,
                    organizations=self._build_api_desired_state(
                        desired_state.get(gi.name, [])
                    ),
                )
                for gi in instances
            ],
            dry_run=dry_run,
        )

        response = await reconcile_glitchtip_project_alerts(
            client=self.qontract_api_client, body=request_data
        )
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()
        glitchtip_instances = glitchtip_instance_query(
            query_func=gqlapi.query
        ).instances
        glitchtip_projects_by_instance: dict[str, list[GlitchtipProjectV1]] = (
            defaultdict(list)
        )
        for glitchtip_project in self.get_projects(query_func=gqlapi.query):
            glitchtip_projects_by_instance[
                glitchtip_project.organization.instance.name
            ].append(glitchtip_project)

        instances_to_reconcile = []
        desired_state = {}
        for glitchtip_instance in glitchtip_instances:
            if self.params.instance and glitchtip_instance.name != self.params.instance:
                continue

            instances_to_reconcile.append(glitchtip_instance)
            glitchtip_jira_bridge_token = (
                self.secret_reader.read_secret(
                    glitchtip_instance.glitchtip_jira_bridge_token
                )
                if glitchtip_instance.glitchtip_jira_bridge_token
                else None
            )
            desired_state[glitchtip_instance.name] = self.fetch_desired_state(
                glitchtip_projects=glitchtip_projects_by_instance[
                    glitchtip_instance.name
                ],
                gjb_alert_url=glitchtip_instance.glitchtip_jira_bridge_alert_url,
                gjb_token=glitchtip_jira_bridge_token,
            )

        if not instances_to_reconcile:
            logging.warning("No Glitchtip instances to reconcile")
            return

        task = await self.reconcile(
            instances=instances_to_reconcile,
            desired_state=desired_state,
            dry_run=dry_run,
        )

        task_result = await glitchtip_project_alerts_task_status(
            client=self.qontract_api_client, task_id=task.id, timeout=300
        )

        if task_result.status == TaskStatus.PENDING:
            logging.error(
                "Glitchtip project alerts task did not complete within the timeout period"
            )
            sys.exit(1)

        for action in task_result.actions or []:
            logging.info(
                f"{action.action_type=} {action.instance=} "
                f"{action.organization=} {action.project=} {action.alert_name=}"
            )

        if task_result.errors:
            logging.error(f"Errors encountered: {len(task_result.errors)}")
            for error in task_result.errors:
                logging.error(f"  - {error}")
            sys.exit(1)
