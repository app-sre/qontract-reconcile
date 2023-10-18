from collections.abc import Sequence
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.glitchtip_project_alerts.integration import (
    GlitchtipProjectAlertsIntegration,
    GlitchtipProjectAlertsIntegrationParams,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.glitchtip_project_alerts.glitchtip_project import (
    GlitchtipInstanceV1,
    GlitchtipOrganizationV1,
    GlitchtipProjectAlertRecipientEmailV1,
    GlitchtipProjectAlertRecipientWebhookV1,
    GlitchtipProjectAlertV1,
    GlitchtipProjectJiraV1,
    GlitchtipProjectsV1,
    JiraBoardV1,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils.glitchtip.client import GlitchtipClient
from reconcile.utils.glitchtip.models import (
    Organization,
    Project,
    ProjectAlert,
    ProjectAlertRecipient,
    RecipientType,
)
from reconcile.utils.secret_reader import SecretReader


@pytest.fixture
def glitchtip_client_mock(mocker: MockerFixture) -> Mock:
    return mocker.create_autospec(spec=GlitchtipClient)


@pytest.fixture
def intg(
    secret_reader: SecretReader, mocker: MockerFixture
) -> GlitchtipProjectAlertsIntegration:
    mocker.patch.object(
        GlitchtipProjectAlertsIntegration, "secret_reader", secret_reader
    )
    return GlitchtipProjectAlertsIntegration(GlitchtipProjectAlertsIntegrationParams())


@pytest.fixture
def projects(
    fx: Fixtures, intg: GlitchtipProjectAlertsIntegration
) -> list[GlitchtipProjectsV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        return fx.get_anymarkup("project_alerts.yml")

    return intg.get_projects(q)


def test_glitchtip_project_alerts_get_projects(
    projects: Sequence[GlitchtipProjectsV1],
) -> None:
    assert projects == [
        GlitchtipProjectsV1(
            name="example",
            projectId=None,
            organization=GlitchtipOrganizationV1(
                name="NASA", instance=GlitchtipInstanceV1(name="glitchtip-dev")
            ),
            alerts=[
                GlitchtipProjectAlertV1(
                    name="example-1",
                    description="Example alert 1",
                    quantity=2,
                    timespanMinutes=2,
                    recipients=[
                        GlitchtipProjectAlertRecipientEmailV1(
                            provider="email-project-members"
                        ),
                        GlitchtipProjectAlertRecipientWebhookV1(
                            provider="webhook",
                            url="https://example.com",
                            urlSecret=None,
                        ),
                    ],
                ),
                GlitchtipProjectAlertV1(
                    name="example-2",
                    description="Example alert 1",
                    quantity=2,
                    timespanMinutes=2,
                    recipients=[
                        GlitchtipProjectAlertRecipientWebhookV1(
                            provider="webhook",
                            url=None,
                            urlSecret=VaultSecret(
                                path="ecret/glitchtip/webhook-url",
                                field="url",
                                version=1,
                                format=None,
                            ),
                        )
                    ],
                ),
            ],
            jira=None,
        ),
        GlitchtipProjectsV1(
            name="no-alerts",
            projectId=None,
            organization=GlitchtipOrganizationV1(
                name="NASA", instance=GlitchtipInstanceV1(name="glitchtip-dev")
            ),
            alerts=None,
            jira=None,
        ),
        GlitchtipProjectsV1(
            name="jira-board-and-alerts",
            projectId=None,
            organization=GlitchtipOrganizationV1(
                name="NASA", instance=GlitchtipInstanceV1(name="glitchtip-dev")
            ),
            alerts=[
                GlitchtipProjectAlertV1(
                    name="example-1",
                    description="Example alert 1",
                    quantity=2,
                    timespanMinutes=2,
                    recipients=[
                        GlitchtipProjectAlertRecipientEmailV1(
                            provider="email-project-members"
                        )
                    ],
                )
            ],
            jira=GlitchtipProjectJiraV1(
                project=None, board=JiraBoardV1(name="JIRA-VIA-BOARD")
            ),
        ),
        GlitchtipProjectsV1(
            name="jira-project",
            projectId=None,
            organization=GlitchtipOrganizationV1(
                name="NASA", instance=GlitchtipInstanceV1(name="glitchtip-dev")
            ),
            alerts=None,
            jira=GlitchtipProjectJiraV1(project="JIRA-VIA-PROJECT", board=None),
        ),
    ]


def test_glitchtip_project_alerts_fetch_desire_state(
    intg: GlitchtipProjectAlertsIntegration,
    projects: Sequence[GlitchtipProjectsV1],
) -> None:
    org = intg.fetch_desired_state(
        projects, gjb_alert_url="http://gjb.com", gjb_token="secret"
    )[0]
    project_1 = org.projects[0]
    assert project_1.alerts == [
        ProjectAlert(
            pk=None,
            name="example-1",
            timespan_minutes=2,
            quantity=2,
            recipients=[
                ProjectAlertRecipient(
                    pk=None,
                    recipient_type=RecipientType.EMAIL,
                    url="",
                ),
                ProjectAlertRecipient(
                    pk=None,
                    recipient_type=RecipientType.WEBHOOK,
                    url="https://example.com",
                ),
            ],
        ),
        ProjectAlert(
            pk=None,
            name="example-2",
            timespan_minutes=2,
            quantity=2,
            recipients=[
                ProjectAlertRecipient(
                    pk=None,
                    recipient_type=RecipientType.WEBHOOK,
                    url="secret",
                )
            ],
        ),
    ]
    project_2 = org.projects[1]
    assert project_2.alerts == []
    project_3 = org.projects[2]
    assert project_3.alerts == [
        ProjectAlert(
            pk=None,
            name="example-1",
            timespan_minutes=2,
            quantity=2,
            recipients=[
                ProjectAlertRecipient(
                    pk=None, recipient_type=RecipientType.EMAIL, url=""
                )
            ],
        ),
        ProjectAlert(
            pk=None,
            name="Jira integration",
            timespan_minutes=1,
            quantity=1,
            recipients=[
                ProjectAlertRecipient(
                    pk=None,
                    recipient_type=RecipientType.WEBHOOK,
                    url="http://gjb.com/JIRA-VIA-BOARD?token=secret",
                )
            ],
        ),
    ]
    project_4 = org.projects[3]
    assert project_4.alerts == [
        ProjectAlert(
            pk=None,
            name="Jira integration",
            timespan_minutes=1,
            quantity=1,
            recipients=[
                ProjectAlertRecipient(
                    pk=None,
                    recipient_type=RecipientType.WEBHOOK,
                    url="http://gjb.com/JIRA-VIA-PROJECT?token=secret",
                )
            ],
        )
    ]


def test_glitchtip_project_alerts_fetch_current_state(
    intg: GlitchtipProjectAlertsIntegration,
    glitchtip_client: GlitchtipClient,
) -> None:
    states = intg.fetch_current_state(glitchtip_client)
    assert len(states) == 4
    assert states["ESA/rosetta-flight-control"].alerts == [
        ProjectAlert(
            pk=14,
            name="alert-2",
            timespan_minutes=2000,
            quantity=1000,
            recipients=[
                ProjectAlertRecipient(
                    pk=20,
                    recipient_type=RecipientType.WEBHOOK,
                    url="https://example.com",
                )
            ],
        ),
        ProjectAlert(
            pk=7,
            name="alert-1",
            timespan_minutes=1000,
            quantity=1000,
            recipients=[
                ProjectAlertRecipient(pk=8, recipient_type=RecipientType.EMAIL, url="")
            ],
        ),
    ]


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry_run", "no_dry_run"])
def test_glitchtip_project_alerts_reconcile(
    intg: GlitchtipProjectAlertsIntegration,
    glitchtip_client_mock: Mock,
    dry_run: bool,
) -> None:
    current_state = {
        "NASA/keep-untouched": Project(
            pk=1,
            name="keep-untouched",
            teams=[],
            alerts=[
                ProjectAlert(
                    pk=1,
                    name="alert-1",
                    timespan_minutes=1000,
                    quantity=1000,
                    recipients=[
                        ProjectAlertRecipient(
                            pk=1, recipient_type=RecipientType.EMAIL, url=""
                        )
                    ],
                ),
            ],
        ),
        "NASA/remove-alert": Project(
            pk=1,
            name="remove-alert",
            teams=[],
            alerts=[
                ProjectAlert(
                    pk=1,
                    name="alert-1",
                    timespan_minutes=1000,
                    quantity=1000,
                    recipients=[],
                ),
            ],
        ),
        "NASA/add-alert": Project(
            pk=1,
            name="add-alert",
            teams=[],
            alerts=[],
        ),
        "NASA/update-alert": Project(
            pk=1,
            name="update-alert",
            teams=[],
            alerts=[
                ProjectAlert(
                    pk=1,
                    name="alert-1",
                    timespan_minutes=1000,
                    quantity=1000,
                    recipients=[
                        ProjectAlertRecipient(
                            pk=20,
                            recipient_type=RecipientType.WEBHOOK,
                            url="https://example.com",
                        )
                    ],
                ),
            ],
        ),
    }
    desired_state = [
        Organization(
            name="NASA",
            slug="nasa",
            projects=[
                Project(
                    name="keep-untouched",
                    teams=[],
                    alerts=[
                        ProjectAlert(
                            name="alert-1",
                            timespan_minutes=1000,
                            quantity=1000,
                            recipients=[
                                ProjectAlertRecipient(
                                    recipient_type=RecipientType.EMAIL, url=""
                                )
                            ],
                        ),
                    ],
                ),
                Project(
                    name="remove-alert",
                    teams=[],
                    alerts=[],
                ),
                Project(
                    name="add-alert",
                    teams=[],
                    alerts=[
                        ProjectAlert(
                            name="alert-1",
                            timespan_minutes=1000,
                            quantity=1000,
                            recipients=[
                                ProjectAlertRecipient(
                                    recipient_type=RecipientType.EMAIL, url=""
                                )
                            ],
                        )
                    ],
                ),
                Project(
                    name="update-alert",
                    teams=[],
                    alerts=[
                        ProjectAlert(
                            name="alert-1",
                            timespan_minutes=1,
                            quantity=1,
                            recipients=[
                                ProjectAlertRecipient(
                                    recipient_type=RecipientType.WEBHOOK,
                                    url="https://example.com",
                                ),
                                ProjectAlertRecipient(
                                    recipient_type=RecipientType.EMAIL, url=""
                                ),
                            ],
                        ),
                    ],
                ),
            ],
            teams=[],
            users=[],
        )
    ]

    intg.reconcile(
        glitchtip_client=glitchtip_client_mock,
        dry_run=dry_run,
        current_state=current_state,
        desired_state=desired_state,
    )
    if dry_run:
        glitchtip_client_mock.create_project_alert.assert_not_called()
        glitchtip_client_mock.delete_project_alert.assert_not_called()
        glitchtip_client_mock.update_project_alert.assert_not_called()
        return

    glitchtip_client_mock.create_project_alert.assert_called_once_with(
        organization_slug="nasa",
        project_slug="add-alert",
        alert=desired_state[0].projects[2].alerts[0],
    )
    glitchtip_client_mock.delete_project_alert.assert_called_once_with(
        organization_slug="nasa",
        project_slug="remove-alert",
        alert_pk=current_state["NASA/remove-alert"].alerts[0].pk,
    )
    glitchtip_client_mock.update_project_alert.assert_called_once_with(
        organization_slug="nasa",
        project_slug="update-alert",
        alert=desired_state[0].projects[3].alerts[0],
    )
