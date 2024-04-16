import logging

import reconcile.gql_definitions.acs.acs_policies as gql_acs_policies
from reconcile.gql_definitions.jira.jira_servers import (
    JiraServerV1,
)
from reconcile.gql_definitions.jira.jira_servers import (
    query as query_jira_servers,
)
from reconcile.utils import gql
from reconcile.utils.acs.notifiers import (
    AcsNotifiersApi,
    JiraCredentials,
    JiraNotifier,
)
from reconcile.utils.differ import diff_iterables
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver


class AcsNotifiersIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration = "acs-notifiers"
        self.qontract_integration_version = make_semver(0, 1, 0)

    @property
    def name(self) -> str:
        return self.qontract_integration

    def _get_escalation_policies(
        self, acs_policies: list[gql_acs_policies.AcsPolicyV1]
    ) -> list[gql_acs_policies.AppEscalationPolicyV1]:
        return list(
            {
                p.integrations.notifiers.jira.escalation_policy.name: p.integrations.notifiers.jira.escalation_policy
                for p in acs_policies
                if p.integrations
                and p.integrations.notifiers
                and p.integrations.notifiers.jira
                and integration_is_enabled(
                    self.qontract_integration,
                    p.integrations.notifiers.jira.escalation_policy.channels.jira_board[
                        0
                    ],
                )
            }.values()
        )

    def get_desired_state(
        self, acs_policies: list[gql_acs_policies.AcsPolicyV1]
    ) -> list[JiraNotifier]:
        return [
            JiraNotifier.from_escalation_policy(ep)
            for ep in self._get_escalation_policies(acs_policies)
        ]

    def get_jira_credentials(
        self, jira_servers: list[JiraServerV1]
    ) -> dict[str, JiraCredentials]:
        return {
            server.server_url: JiraCredentials(
                url=server.server_url,
                username=server.username,
                token=self.secret_reader.read_secret(server.token),
            )
            for server in jira_servers
        }

    def reconcile(
        self,
        current_state: list[JiraNotifier],
        desired_state: list[JiraNotifier],
        acs_api: AcsNotifiersApi,
        jira_credentials: dict[str, JiraCredentials],
        dry_run: bool,
    ) -> None:
        diff = diff_iterables(
            current=current_state, desired=desired_state, key=lambda x: x.name
        )
        for a in diff.add.values():
            logging.info(f"Create Jira notifier: {a.name}")
            if not dry_run:
                acs_api.create_jira_notifier(
                    a,
                    jira_credentials=jira_credentials[a.url],
                )
        for c in diff.change.values():
            logging.info(f"Update Jira notifier: {c.desired.name}")
            if not dry_run:
                acs_api.update_jira_notifier(
                    c.desired,
                    jira_credentials=jira_credentials[c.desired.url],
                )
        for d in diff.delete.values():
            logging.info(f"Delete Jira notifier: {d.name}")
            if not dry_run:
                acs_api.delete_jira_notifier(d)

    def run(
        self,
        dry_run: bool,
    ) -> None:
        gql_api_query = gql.get_api().query
        jira_credentials = self.get_jira_credentials(
            query_jira_servers(query_func=gql_api_query).jira_servers or []
        )
        desired_state = self.get_desired_state(
            gql_acs_policies.query(query_func=gql_api_query).acs_policies or []
        )
        instance = AcsNotifiersApi.get_acs_instance(query_func=gql_api_query)
        with AcsNotifiersApi(
            url=instance.url, token=self.secret_reader.read_secret(instance.credentials)
        ) as acs_api:
            current_state = acs_api.get_jira_notifiers()
            self.reconcile(
                current_state=current_state,
                desired_state=desired_state,
                acs_api=acs_api,
                jira_credentials=jira_credentials,
                dry_run=dry_run,
            )
