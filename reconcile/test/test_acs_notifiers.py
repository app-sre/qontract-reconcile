import copy
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.acs_notifiers import AcsNotifiersIntegration
from reconcile.gql_definitions.acs.acs_policies import (
    AcsPolicyIntegrationNotifierJiraV1,
    AcsPolicyIntegrationNotifiersV1,
    AcsPolicyIntegrationsV1,
    AcsPolicyScopeClusterV1,
    AcsPolicyScopeNamespaceV1,
    AcsPolicyV1,
    AppEscalationPolicyChannelsV1,
    AppEscalationPolicyV1,
    DisableJiraBoardAutomationsV1,
    JiraBoardV1,
    JiraServerV1,
    JiraSeverityPriorityMappingsV1,
    SeverityPriorityMappingV1,
)
from reconcile.utils.acs.notifiers import (
    AcsNotifiersApi,
    JiraCredentials,
    JiraNotifier,
    SeverityPriorityMapping,
)


@pytest.fixture
def severity_priority_mapping() -> SeverityPriorityMapping:
    return SeverityPriorityMapping(severity="critical", priority="Critical")


@pytest.fixture
def severity_priority_mapping_api_payload() -> dict[str, str]:
    return {
        "severity": "CRITICAL_SEVERITY",
        "priorityName": "Critical",
    }


def test_severity_priority_mappings_to_api(
    severity_priority_mapping: SeverityPriorityMapping,
    severity_priority_mapping_api_payload: dict[str, str],
) -> None:
    assert severity_priority_mapping.to_api() == severity_priority_mapping_api_payload


def test_severity_priority_mappings_from_api(
    severity_priority_mapping: SeverityPriorityMapping,
    severity_priority_mapping_api_payload: dict[str, str],
) -> None:
    assert (
        SeverityPriorityMapping.from_api(severity_priority_mapping_api_payload)
        == severity_priority_mapping
    )


@pytest.fixture
def jira_credentials() -> JiraCredentials:
    return JiraCredentials(
        url="https://jira.example.com",
        username="jirabot",
        token="topsecret",
    )


@pytest.fixture
def jira_notifier(
    severity_priority_mapping: SeverityPriorityMapping,
    jira_credentials: JiraCredentials,
) -> JiraNotifier:
    return JiraNotifier(
        name="jira-notifier-1",
        board="JIRAPLAY",
        url=jira_credentials.url,
        issue_type="Task",
        severity_priority_mappings=[severity_priority_mapping],
        custom_fields={"security": {"id": "0"}},
    )


@pytest.fixture
def jira_notifier_api_payload(
    severity_priority_mapping: SeverityPriorityMapping,
    jira_credentials: JiraCredentials,
) -> dict[str, Any]:
    return {
        "name": "jira-notifier-1",
        "type": "jira",
        "uiEndpoint": "https://acs.example.com",
        "labelDefault": "JIRAPLAY",
        "jira": {
            "url": jira_credentials.url,
            "username": jira_credentials.username,
            "password": jira_credentials.token,
            "issueType": "Task",
            "priorityMappings": [severity_priority_mapping.to_api()],
            "defaultFieldsJson": '{"security": {"id": "0"}}',
        },
    }


def test_jira_notifier_to_api(
    jira_notifier: JiraNotifier,
    jira_credentials: JiraCredentials,
    jira_notifier_api_payload: dict[str, Any],
) -> None:
    assert (
        jira_notifier.to_api(
            ui_endpoint="https://acs.example.com", jira_credentials=jira_credentials
        )
        == jira_notifier_api_payload
    )


@pytest.fixture
def acs_notifier_api() -> AcsNotifiersApi:
    return AcsNotifiersApi(
        url="https://acs.example.com",
        token="topsecret",
    )


@pytest.fixture
def acs_notifier_api_notifiers_api_payload(
    jira_notifier: JiraNotifier,
    jira_credentials: JiraCredentials,
) -> list[Any]:
    return [
        jira_notifier.to_api(
            ui_endpoint="https://acs.example.com", jira_credentials=jira_credentials
        )
    ]


def test_acs_notifier_api_get_notifiers(
    mocker: MockerFixture,
    acs_notifier_api_notifiers_api_payload: list[Any],
    acs_notifier_api: AcsNotifiersApi,
) -> None:
    generic_request_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.generic_request_json"
    )
    generic_request_mock.return_value = {
        "notifiers": acs_notifier_api_notifiers_api_payload
    }

    assert acs_notifier_api.get_notifiers() == acs_notifier_api_notifiers_api_payload
    generic_request_mock.assert_called_once_with("/v1/notifiers", "GET")


def test_acs_notifier_api_get_jira_notifiers(
    mocker: MockerFixture,
    acs_notifier_api_notifiers_api_payload: list[Any],
    acs_notifier_api: AcsNotifiersApi,
    jira_notifier: JiraNotifier,
) -> None:
    get_notifiers_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.get_notifiers"
    )
    get_notifiers_mock.return_value = acs_notifier_api_notifiers_api_payload

    assert acs_notifier_api.get_jira_notifiers() == [jira_notifier]


def test_get_notifier_id_by_name(
    mocker: MockerFixture,
    acs_notifier_api_notifiers_api_payload: list[Any],
    acs_notifier_api: AcsNotifiersApi,
) -> None:
    get_notifiers_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.get_notifiers"
    )
    get_notifiers_mock.return_value = acs_notifier_api_notifiers_api_payload
    acs_notifier_api_notifiers_api_payload[0]["id"] = "jira-notifier-id-1"

    assert (
        acs_notifier_api.get_notifier_id_by_name("jira-notifier-1")
        == "jira-notifier-id-1"
    )
    get_notifiers_mock.assert_called_once()


def test_update_jira_notifier(
    mocker: MockerFixture,
    acs_notifier_api: AcsNotifiersApi,
    jira_notifier: JiraNotifier,
    jira_credentials: JiraCredentials,
) -> None:
    get_notifier_id_by_name_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.get_notifier_id_by_name"
    )
    get_notifier_id_by_name_mock.return_value = "jira-notifier-id-1"
    generic_request_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.generic_request"
    )

    acs_notifier_api.update_jira_notifier(jira_notifier, jira_credentials)
    get_notifier_id_by_name_mock.assert_called_once_with(jira_notifier.name)
    body = jira_notifier.to_api(acs_notifier_api.url, jira_credentials)
    generic_request_mock.assert_called_once_with(
        "/v1/notifiers/jira-notifier-id-1", "PUT", body
    )


def test_create_jira_notifier(
    mocker: MockerFixture,
    acs_notifier_api: AcsNotifiersApi,
    jira_notifier: JiraNotifier,
    jira_credentials: JiraCredentials,
) -> None:
    generic_request_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.generic_request"
    )
    acs_notifier_api.create_jira_notifier(jira_notifier, jira_credentials)
    body = jira_notifier.to_api(acs_notifier_api.url, jira_credentials)
    generic_request_mock.assert_called_once_with("/v1/notifiers", "POST", body)


def test_delete_jira_notifier(
    mocker: MockerFixture,
    acs_notifier_api: AcsNotifiersApi,
    jira_notifier: JiraNotifier,
) -> None:
    get_notifier_id_by_name_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.get_notifier_id_by_name"
    )
    get_notifier_id_by_name_mock.return_value = "jira-notifier-id-1"
    generic_request_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.generic_request"
    )
    acs_notifier_api.delete_jira_notifier(jira_notifier)
    get_notifier_id_by_name_mock.assert_called_once_with(jira_notifier.name)
    generic_request_mock.assert_called_once_with(
        "/v1/notifiers/jira-notifier-id-1", "DELETE"
    )


@pytest.fixture
def acs_notifier_integration() -> AcsNotifiersIntegration:
    return AcsNotifiersIntegration()


@pytest.fixture
def escalation_policy() -> AppEscalationPolicyV1:
    return AppEscalationPolicyV1(
        name="notifier-1",
        channels=AppEscalationPolicyChannelsV1(
            jiraBoard=[
                JiraBoardV1(
                    name="JIRAPLAY",
                    server=JiraServerV1(
                        serverUrl="https://jira.example.com",
                    ),
                    severityPriorityMappings=JiraSeverityPriorityMappingsV1(
                        name="sp",
                        mappings=[
                            SeverityPriorityMappingV1(
                                severity="critical", priority="Critical"
                            )
                        ],
                    ),
                    issueType="Task",
                    issueSecurityId="0",
                    disable=DisableJiraBoardAutomationsV1(integrations=[]),
                )
            ],
            jiraComponent="",
            jiraLabels=[],
        ),
    )


@pytest.fixture
def acs_policies(
    escalation_policy: AppEscalationPolicyV1,
) -> list[AcsPolicyV1]:
    return [
        AcsPolicyV1(
            name="acs-policy-1",
            description="CVEs within app-sre clusters with CVSS score gte to 7 and fixable",
            severity="high",
            integrations=AcsPolicyIntegrationsV1(
                notifiers=AcsPolicyIntegrationNotifiersV1(
                    jira=AcsPolicyIntegrationNotifierJiraV1(
                        escalationPolicy=escalation_policy,
                    ),
                ),
            ),
            categories=["vulnerability-management"],
            scope=AcsPolicyScopeClusterV1(
                level="cluster",
                clusters=[],
            ),
            conditions=[],
        ),
        AcsPolicyV1(
            name="acs-policy-2",
            description="image security policy violations of critical severity within app-sre namespaces",
            severity="critical",
            integrations=AcsPolicyIntegrationsV1(
                notifiers=AcsPolicyIntegrationNotifiersV1(
                    jira=AcsPolicyIntegrationNotifierJiraV1(
                        escalationPolicy=escalation_policy,
                    ),
                ),
            ),
            categories=["vulnerability-management", "devops-best-practices"],
            scope=AcsPolicyScopeNamespaceV1(
                level="namespace",
                namespaces=[],
            ),
            conditions=[],
        ),
    ]


def test_integration_get_escalation_policies(
    acs_notifier_integration: AcsNotifiersIntegration,
    acs_policies: list[AcsPolicyV1],
    escalation_policy: AppEscalationPolicyV1,
) -> None:
    result = acs_notifier_integration._get_escalation_policies(acs_policies)

    assert len(acs_policies) > 1
    assert len(result) == 1
    assert result[0] == escalation_policy


def test_build_jira_notifier_from_ecalation_policy(
    escalation_policy: AppEscalationPolicyV1,
    jira_notifier: JiraNotifier,
) -> None:
    assert JiraNotifier.from_escalation_policy(escalation_policy) == jira_notifier


def test_get_desired_state(
    acs_notifier_integration: AcsNotifiersIntegration,
    acs_policies: list[AcsPolicyV1],
    jira_notifier: JiraNotifier,
) -> None:
    assert acs_notifier_integration.get_desired_state(acs_policies) == [jira_notifier]


def test_reconcile(
    mocker: MockerFixture,
    acs_notifier_integration: AcsNotifiersIntegration,
    acs_notifier_api: AcsNotifiersApi,
    jira_credentials: JiraCredentials,
    jira_notifier: JiraNotifier,
) -> None:
    notifier_to_add = copy.deepcopy(jira_notifier)
    notifier_to_add.name = "jira-notifier-to-add"
    notifier_to_update_current = copy.deepcopy(jira_notifier)
    notifier_to_update_current.name = "jira-notifier-to-update"
    notifier_to_update_current.issue_type = "Task"
    notifier_to_update_desired = copy.deepcopy(jira_notifier)
    notifier_to_update_desired.name = "jira-notifier-to-update"
    notifier_to_update_current.issue_type = "Bug"
    notifier_to_delete = copy.deepcopy(jira_notifier)
    notifier_to_delete.name = "jira-notifier-to-delete"

    current_state = [notifier_to_delete, notifier_to_update_current]
    desired_state = [notifier_to_add, notifier_to_update_desired]

    create_jira_notifier_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.create_jira_notifier"
    )
    update_jira_notifier_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.update_jira_notifier"
    )

    delete_jira_notifier_mock = mocker.patch(
        "reconcile.utils.acs.notifiers.AcsNotifiersApi.delete_jira_notifier"
    )
    acs_notifier_integration.reconcile(
        current_state,
        desired_state,
        acs_notifier_api,
        {jira_credentials.url: jira_credentials},
        dry_run=False,
    )

    create_jira_notifier_mock.assert_called_once_with(
        notifier_to_add, jira_credentials=jira_credentials
    )
    update_jira_notifier_mock.assert_called_once_with(
        notifier_to_update_desired, jira_credentials=jira_credentials
    )
    delete_jira_notifier_mock.assert_called_once_with(notifier_to_delete)
