import logging
from collections import defaultdict
from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Any,
    Optional,
)
from urllib.parse import quote

from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    query as glitchtip_instance_query,
)
from reconcile.gql_definitions.glitchtip_project_alerts.glitchtip_project import (
    GlitchtipProjectAlertRecipientEmailV1,
    GlitchtipProjectAlertRecipientV1,
    GlitchtipProjectAlertRecipientWebhookV1,
    GlitchtipProjectsV1,
)
from reconcile.gql_definitions.glitchtip_project_alerts.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.utils import gql
from reconcile.utils.differ import diff_iterables
from reconcile.utils.glitchtip.client import GlitchtipClient
from reconcile.utils.glitchtip.models import (
    Organization,
    Project,
    ProjectAlert,
    ProjectAlertRecipient,
    RecipientType,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "glitchtip-project-alerts"
GJB_ALERT_NAME = "Glitchtip-Jira-Bridge-Integration"
ProjectStates = dict[str, Project]


class GlitchtipProjectAlertsIntegrationParams(PydanticRunParams):
    instance: Optional[str] = None


class GlitchtipProjectAlertsIntegration(
    QontractReconcileIntegration[GlitchtipProjectAlertsIntegrationParams]
):
    """Manage Glitchtip project alerts."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(self) -> Optional[dict[str, Any]]:
        return {"projects": [c.dict() for c in self.get_projects(gql.get_api().query)]}

    def get_projects(self, query_func: Callable) -> list[GlitchtipProjectsV1]:
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

    def fetch_desired_state(
        self,
        glitchtip_projects: Iterable[GlitchtipProjectsV1],
        gjb_alert_url: str | None,
        gjb_token: str | None,
    ) -> list[Organization]:
        organizations: dict[str, Organization] = {}
        for glitchtip_project in glitchtip_projects:
            organization = organizations.setdefault(
                glitchtip_project.organization.name,
                Organization(name=glitchtip_project.organization.name),
            )
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
            if glitchtip_project.jira and gjb_alert_url:
                if not (jira_project_key := glitchtip_project.jira.project):
                    if glitchtip_project.jira.board:
                        jira_project_key = glitchtip_project.jira.board.name

                # this shouldn't happen, because our schemas enforce it
                if not jira_project_key:
                    raise ValueError(
                        "Either jira.project or jira.board must be set for Jira integration"
                    )

                url = f"{gjb_alert_url}/{jira_project_key}"
                if gjb_token:
                    url += f"?token={quote(gjb_token)}"

                alerts.append(
                    ProjectAlert(
                        name=GJB_ALERT_NAME,
                        timespan_minutes=1,
                        quantity=1,
                        recipients=[
                            ProjectAlertRecipient(
                                recipient_type=RecipientType.WEBHOOK,
                                url=url,
                            )
                        ],
                    )
                )
            project = Project(
                name=glitchtip_project.name,
                platform=None,
                slug=glitchtip_project.project_id
                if glitchtip_project.project_id
                else "",
                alerts=alerts,
            )

            organization.projects.append(project)
        return list(organizations.values())

    def fetch_current_state(self, glitchtip_client: GlitchtipClient) -> ProjectStates:
        organizations = glitchtip_client.organizations()
        for organization in organizations:
            organization.projects = glitchtip_client.projects(
                organization_slug=organization.slug
            )
            for proj in organization.projects:
                proj.alerts = glitchtip_client.project_alerts(
                    organization_slug=organization.slug, project_slug=proj.slug
                )

        return {
            f"{org.name}/{project.slug}": project
            for org in organizations
            for project in org.projects
        }

    def reconcile(
        self,
        glitchtip_client: GlitchtipClient,
        dry_run: bool,
        current_state: ProjectStates,
        desired_state: Iterable[Organization],
    ) -> None:
        for org in desired_state:
            for desired_project in org.projects:
                current_project = current_state.get(
                    f"{org.name}/{desired_project.slug}",
                )
                if not current_project:
                    # project does not exist yet - skip and try it again later
                    continue

                diff_result = diff_iterables(
                    current_project.alerts,
                    desired_project.alerts,
                    key=lambda g: g.name,
                    equal=lambda g1, g2: g1 == g2,
                )

                for alert_to_add in diff_result.add.values():
                    logging.info(
                        [
                            "create_project_alert",
                            f"{org.name}/{desired_project.slug}/{alert_to_add.name}",
                        ]
                    )
                    if not dry_run:
                        glitchtip_client.create_project_alert(
                            organization_slug=org.slug,
                            project_slug=desired_project.slug,
                            alert=alert_to_add,
                        )

                for alert_to_remove in diff_result.delete.values():
                    if not alert_to_remove.pk:
                        # this can't happend - just make mypy happy
                        continue
                    logging.info(
                        [
                            "delete_project_alert",
                            f"{org.name}/{desired_project.slug}/{alert_to_remove.name}",
                        ]
                    )
                    if not dry_run:
                        glitchtip_client.delete_project_alert(
                            organization_slug=org.slug,
                            project_slug=desired_project.slug,
                            alert_pk=alert_to_remove.pk,
                        )

                for diff_pair in diff_result.change.values():
                    alert_to_update = diff_pair.desired
                    alert_to_update.pk = diff_pair.current.pk
                    logging.info(
                        [
                            "update_project_alert",
                            f"{org.name}/{desired_project.slug}/{alert_to_update.name}",
                        ]
                    )
                    if not dry_run:
                        glitchtip_client.update_project_alert(
                            organization_slug=org.slug,
                            project_slug=desired_project.slug,
                            alert=alert_to_update,
                        )

    def run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()
        # data
        glitchtip_instances = glitchtip_instance_query(
            query_func=gqlapi.query
        ).instances
        glitchtip_projects_by_instance: dict[
            str, list[GlitchtipProjectsV1]
        ] = defaultdict(list)
        for glitchtip_project in self.get_projects(query_func=gqlapi.query):
            glitchtip_projects_by_instance[
                glitchtip_project.organization.instance.name
            ].append(glitchtip_project)

        for glitchtip_instance in glitchtip_instances:
            if self.params.instance and glitchtip_instance.name != self.params.instance:
                continue
            glitchtip_jira_bridge_token = (
                self.secret_reader.read_secret(
                    glitchtip_instance.glitchtip_jira_bridge_token
                )
                if glitchtip_instance.glitchtip_jira_bridge_token
                else None
            )

            glitchtip_client = GlitchtipClient(
                host=glitchtip_instance.console_url,
                token=self.secret_reader.read_secret(
                    glitchtip_instance.automation_token
                ),
                read_timeout=glitchtip_instance.read_timeout,
                max_retries=glitchtip_instance.max_retries,
            )
            current_state = self.fetch_current_state(glitchtip_client=glitchtip_client)
            desired_state = self.fetch_desired_state(
                glitchtip_projects=glitchtip_projects_by_instance[
                    glitchtip_instance.name
                ],
                gjb_alert_url=glitchtip_instance.glitchtip_jira_bridge_alert_url,
                gjb_token=glitchtip_jira_bridge_token,
            )
            self.reconcile(
                glitchtip_client=glitchtip_client,
                dry_run=dry_run,
                current_state=current_state,
                desired_state=desired_state,
            )
