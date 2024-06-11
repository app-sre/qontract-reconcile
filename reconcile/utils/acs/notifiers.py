import json
from typing import Any

from pydantic import BaseModel

from reconcile.gql_definitions.acs.acs_policies import AppEscalationPolicyV1
from reconcile.utils.acs.base import AcsBaseApi


class JiraCredentials(BaseModel):
    url: str
    username: str
    token: str


class SeverityPriorityMapping(BaseModel):
    severity: str
    priority: str

    @staticmethod
    def from_api(mapping: dict[str, str]) -> "SeverityPriorityMapping":
        return SeverityPriorityMapping(
            severity=mapping["severity"].replace("_SEVERITY", "").lower(),
            priority=mapping["priorityName"],
        )

    def to_api(self) -> Any:
        return {
            "severity": f"{self.severity.upper()}_SEVERITY",
            "priorityName": self.priority,
        }


class JiraNotifier(BaseModel):
    name: str
    board: str
    url: str
    issue_type: str | None
    severity_priority_mappings: list[SeverityPriorityMapping]
    custom_fields: dict[str, Any] | None

    @staticmethod
    def from_api(notifier: dict[str, Any]) -> "JiraNotifier":
        notifier_jira = notifier["jira"]
        return JiraNotifier(
            name=notifier["name"],
            board=notifier["labelDefault"],
            url=notifier_jira["url"],
            issue_type=notifier_jira["issueType"],
            severity_priority_mappings=sorted(
                [
                    SeverityPriorityMapping.from_api(mapping)
                    for mapping in notifier_jira["priorityMappings"]
                ],
                key=lambda m: m.severity,
            ),
            custom_fields=json.loads(notifier_jira.get("defaultFieldsJson") or "{}"),
        )

    def to_api(self, ui_endpoint: str, jira_credentials: JiraCredentials) -> Any:
        return {
            "name": self.name,
            "type": "jira",
            "uiEndpoint": ui_endpoint,
            "labelDefault": self.board,
            "jira": {
                "url": jira_credentials.url,
                "username": jira_credentials.username,
                "password": jira_credentials.token,
                "issueType": self.issue_type or "Task",
                "priorityMappings": [
                    mapping.to_api() for mapping in self.severity_priority_mappings
                ],
                "defaultFieldsJson": json.dumps(self.custom_fields or {}),
            },
        }

    @staticmethod
    def from_escalation_policy(
        escalation_policy: AppEscalationPolicyV1,
    ) -> "JiraNotifier":
        jira_board = escalation_policy.channels.jira_board[0]

        custom_fields: dict[str, Any] = {}
        if jira_board.issue_security_id:
            custom_fields["security"] = {"id": jira_board.issue_security_id}
        if escalation_policy.channels.jira_component:
            custom_fields["components"] = [
                {"name": escalation_policy.channels.jira_component}
            ]
        if escalation_policy.channels.jira_labels:
            custom_fields["labels"] = escalation_policy.channels.jira_labels

        return JiraNotifier(
            name=f"jira-{escalation_policy.name}",
            board=jira_board.name,
            url=jira_board.server.server_url,
            issue_type=jira_board.issue_type or "Task",
            severity_priority_mappings=sorted(
                [
                    SeverityPriorityMapping(**vars(sp))
                    for sp in jira_board.severity_priority_mappings.mappings
                ],
                key=lambda m: m.severity,
            ),
            custom_fields=custom_fields,
        )


class AcsNotifiersApi(AcsBaseApi):
    """
    Implements methods to support reconcile operations against the ACS NotifiersService api
    """

    def get_notifiers(self) -> list[Any]:
        return self.generic_request_json("/v1/notifiers", "GET")["notifiers"]

    def get_jira_notifiers(self) -> list[JiraNotifier]:
        return [
            JiraNotifier.from_api(notifier)
            for notifier in self.get_notifiers()
            if notifier["type"] == "jira"
        ]

    def get_notifier_id_by_name(self, name: str) -> str:
        return [n["id"] for n in self.get_notifiers() if n["name"] == name][0]

    def update_jira_notifier(
        self, jira_notifier: JiraNotifier, jira_credentials: JiraCredentials
    ) -> None:
        notifier_id = self.get_notifier_id_by_name(jira_notifier.name)
        body = jira_notifier.to_api(self.url, jira_credentials)
        self.generic_request(f"/v1/notifiers/{notifier_id}", "PUT", body)

    def create_jira_notifier(
        self, jira_notifier: JiraNotifier, jira_credentials: JiraCredentials
    ) -> None:
        body = jira_notifier.to_api(self.url, jira_credentials)
        self.generic_request("/v1/notifiers", "POST", body)

    def delete_jira_notifier(self, jira_notifier: JiraNotifier) -> None:
        notifier_id = self.get_notifier_id_by_name(jira_notifier.name)
        self.generic_request(f"/v1/notifiers/{notifier_id}", "DELETE")
