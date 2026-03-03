"""Tests for qontract_utils.glitchtip_api module."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from qontract_utils.glitchtip_api import (
    GlitchtipApi,
    GlitchtipApiCallContext,
    Organization,
    Project,
    ProjectAlert,
    ProjectAlertRecipient,
    RecipientType,
)
from qontract_utils.glitchtip_api.client import get_next_url, parse_link_header

# --- Model Tests ---


def test_organization_model() -> None:
    """Test Organization model validation."""
    org = Organization.model_validate({"id": 1, "name": "my-org", "slug": "my-org"})
    assert org.pk == 1
    assert org.name == "my-org"
    assert org.slug == "my-org"


def test_project_model() -> None:
    """Test Project model validation."""
    project = Project.model_validate(
        {"id": 2, "name": "my-project", "slug": "my-project"}
    )
    assert project.pk == 2
    assert project.name == "my-project"
    assert project.slug == "my-project"


def test_project_alert_model() -> None:
    """Test ProjectAlert model validation with camelCase aliases."""
    alert = ProjectAlert.model_validate(
        {
            "id": 10,
            "name": "high-error-rate",
            "timespanMinutes": 5,
            "quantity": 100,
            "alertRecipients": [
                {"id": 1, "recipientType": "email", "url": ""},
                {
                    "id": 2,
                    "recipientType": "webhook",
                    "url": "https://example.com/hook",
                },
            ],
        }
    )
    assert alert.pk == 10
    assert alert.name == "high-error-rate"
    assert alert.timespan_minutes == 5
    assert alert.quantity == 100
    assert len(alert.recipients) == 2
    assert alert.recipients[0].recipient_type == RecipientType.EMAIL
    assert alert.recipients[1].recipient_type == RecipientType.WEBHOOK
    assert alert.recipients[1].url == "https://example.com/hook"


def test_project_alert_model_empty_recipients() -> None:
    """Test ProjectAlert model with no recipients."""
    alert = ProjectAlert.model_validate(
        {
            "name": "my-alert",
            "timespanMinutes": 1,
            "quantity": 10,
        }
    )
    assert alert.recipients == []


def test_project_alert_recipient_model() -> None:
    """Test ProjectAlertRecipient model validation."""
    recipient = ProjectAlertRecipient.model_validate(
        {
            "id": 5,
            "recipientType": "webhook",
            "url": "https://example.com/hook",
        }
    )
    assert recipient.pk == 5
    assert recipient.recipient_type == RecipientType.WEBHOOK
    assert recipient.url == "https://example.com/hook"


def test_recipient_type_enum() -> None:
    """Test RecipientType enum values."""
    assert RecipientType.EMAIL == "email"
    assert RecipientType.WEBHOOK == "webhook"


# --- Equality Tests ---

_WEBHOOK = ProjectAlertRecipient(
    recipient_type=RecipientType.WEBHOOK, url="https://example.com/hook"
)
_EMAIL = ProjectAlertRecipient(recipient_type=RecipientType.EMAIL, url="")


@pytest.mark.parametrize(
    ("r1", "r2", "equal"),
    [
        pytest.param(
            ProjectAlertRecipient(
                pk=1,
                recipient_type=RecipientType.WEBHOOK,
                url="https://example.com/hook",
            ),
            ProjectAlertRecipient(
                pk=99,
                recipient_type=RecipientType.WEBHOOK,
                url="https://example.com/hook",
            ),
            True,
            id="same-config-different-pk",
        ),
        pytest.param(
            ProjectAlertRecipient(recipient_type=RecipientType.EMAIL, url=""),
            ProjectAlertRecipient(recipient_type=RecipientType.WEBHOOK, url=""),
            False,
            id="different-type",
        ),
        pytest.param(
            ProjectAlertRecipient(
                recipient_type=RecipientType.WEBHOOK, url="https://a.com"
            ),
            ProjectAlertRecipient(
                recipient_type=RecipientType.WEBHOOK, url="https://b.com"
            ),
            False,
            id="different-url",
        ),
    ],
)
def test_project_alert_recipient_eq(
    r1: ProjectAlertRecipient, r2: ProjectAlertRecipient, *, equal: bool
) -> None:
    assert (r1 == r2) is equal


def test_project_alert_recipient_eq_non_recipient_raises() -> None:
    """Comparing recipient with non-recipient raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        _EMAIL == "not-a-recipient"  # noqa: B015


@pytest.mark.parametrize(
    ("a1", "a2", "equal"),
    [
        pytest.param(
            ProjectAlert(pk=1, name="alert-a", timespan_minutes=5, quantity=100),
            ProjectAlert(pk=99, name="alert-b", timespan_minutes=5, quantity=100),
            True,
            id="same-config-different-pk-and-name",
        ),
        pytest.param(
            ProjectAlert(name="alert", timespan_minutes=5, quantity=100),
            ProjectAlert(name="alert", timespan_minutes=10, quantity=100),
            False,
            id="different-timespan",
        ),
        pytest.param(
            ProjectAlert(name="alert", timespan_minutes=5, quantity=100),
            ProjectAlert(name="alert", timespan_minutes=5, quantity=200),
            False,
            id="different-quantity",
        ),
        pytest.param(
            ProjectAlert(
                name="alert",
                timespan_minutes=5,
                quantity=100,
                recipients=[_EMAIL, _WEBHOOK],
            ),
            ProjectAlert(
                name="alert",
                timespan_minutes=5,
                quantity=100,
                recipients=[_WEBHOOK, _EMAIL],
            ),
            True,
            id="recipient-order-does-not-matter",
        ),
        pytest.param(
            ProjectAlert(
                name="alert", timespan_minutes=5, quantity=100, recipients=[_EMAIL]
            ),
            ProjectAlert(
                name="alert", timespan_minutes=5, quantity=100, recipients=[_WEBHOOK]
            ),
            False,
            id="different-recipients",
        ),
    ],
)
def test_project_alert_eq(a1: ProjectAlert, a2: ProjectAlert, *, equal: bool) -> None:
    assert (a1 == a2) is equal


def test_project_alert_eq_non_alert_raises() -> None:
    """Comparing alert with non-alert raises NotImplementedError."""
    a = ProjectAlert(name="alert", timespan_minutes=5, quantity=100)
    with pytest.raises(NotImplementedError):
        a == "not-an-alert"  # noqa: B015


# --- Link Header Parsing Tests ---


def test_parse_link_header_with_next() -> None:
    """Test parsing Link header with next page."""
    header = '<https://glitchtip.example.com/api/0/orgs/?cursor=abc>; rel="next"; results="true"'
    result = parse_link_header(header)
    assert "next" in result
    assert (
        result["next"]["url"] == "https://glitchtip.example.com/api/0/orgs/?cursor=abc"
    )
    assert result["next"]["results"] == "true"


def test_parse_link_header_no_results() -> None:
    """Test parsing Link header where next has no results."""
    header = '<https://glitchtip.example.com/api/0/orgs/?cursor=abc>; rel="next"; results="false"'
    result = parse_link_header(header)
    assert result["next"]["results"] == "false"


def test_parse_link_header_empty() -> None:
    """Test parsing empty Link header."""
    result = parse_link_header("")
    assert result == {}


def test_get_next_url_with_results() -> None:
    """Test _get_next_url returns URL when next page has results."""
    response = MagicMock(spec=httpx.Response)
    response.headers = {
        "Link": '<https://example.com/next>; rel="next"; results="true"'
    }
    url = get_next_url(response)
    assert url == "https://example.com/next"


def test_get_next_url_without_results() -> None:
    """Test _get_next_url returns None when next page has no results."""
    response = MagicMock(spec=httpx.Response)
    response.headers = {
        "Link": '<https://example.com/next>; rel="next"; results="false"'
    }
    url = get_next_url(response)
    assert url is None


def test_get_next_url_no_link_header() -> None:
    """Test _get_next_url returns None when no Link header."""
    response = MagicMock(spec=httpx.Response)
    response.headers = {}
    url = get_next_url(response)
    assert url is None


# --- Client Tests ---


@pytest.fixture
def mock_httpx_client() -> MagicMock:
    """Mock httpx.Client."""
    return MagicMock(spec=httpx.Client)


@pytest.fixture
def glitchtip_api(mock_httpx_client: MagicMock) -> GlitchtipApi:
    """Create GlitchtipApi instance with mocked httpx client."""
    with patch("qontract_utils.glitchtip_api.client.httpx.Client") as mock_cls:
        mock_cls.return_value = mock_httpx_client
        return GlitchtipApi(
            host="https://glitchtip.example.com",
            token="test-token",
        )


def _make_response(data: list | dict, link: str = "") -> MagicMock:
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = data
    response.headers = {"Link": link} if link else {}
    return response


def test_glitchtip_api_host_stripped() -> None:
    """Test that trailing slash is stripped from host."""
    with patch("qontract_utils.glitchtip_api.client.httpx.Client"):
        api = GlitchtipApi(host="https://glitchtip.example.com/", token="token")
    assert api.host == "https://glitchtip.example.com"


def test_organizations_single_page(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test organizations() fetches single page."""
    mock_httpx_client.get.return_value = _make_response(
        [
            {"id": 1, "name": "org-1", "slug": "org-1"},
            {"id": 2, "name": "org-2", "slug": "org-2"},
        ]
    )

    orgs = glitchtip_api.organizations()

    assert len(orgs) == 2
    assert orgs[0].name == "org-1"
    assert orgs[1].name == "org-2"
    mock_httpx_client.get.assert_called_once_with(
        "/api/0/organizations/", params={"limit": 100}
    )


def test_organizations_pagination(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test organizations() fetches all pages via pagination."""
    page1 = _make_response(
        [{"id": 1, "name": "org-1", "slug": "org-1"}],
        link='<https://glitchtip.example.com/api/0/organizations/?cursor=abc>; rel="next"; results="true"',
    )
    page2 = _make_response([{"id": 2, "name": "org-2", "slug": "org-2"}])

    mock_httpx_client.get.side_effect = [page1, page2]

    orgs = glitchtip_api.organizations()

    assert len(orgs) == 2
    assert orgs[0].name == "org-1"
    assert orgs[1].name == "org-2"
    assert mock_httpx_client.get.call_count == 2


def test_projects(glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock) -> None:
    """Test projects() fetches projects for an organization."""
    mock_httpx_client.get.return_value = _make_response(
        [
            {"id": 1, "name": "project-1", "slug": "project-1"},
        ]
    )

    projects = glitchtip_api.projects("my-org")

    assert len(projects) == 1
    assert projects[0].slug == "project-1"
    mock_httpx_client.get.assert_called_once_with(
        "/api/0/organizations/my-org/projects/", params={"limit": 100}
    )


def test_project_alerts(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test project_alerts() fetches alerts for a project."""
    mock_httpx_client.get.return_value = _make_response(
        [
            {
                "id": 10,
                "name": "alert-1",
                "timespanMinutes": 5,
                "quantity": 100,
                "alertRecipients": [],
            }
        ]
    )

    alerts = glitchtip_api.project_alerts("my-org", "my-project")

    assert len(alerts) == 1
    assert alerts[0].name == "alert-1"
    mock_httpx_client.get.assert_called_once_with(
        "/api/0/projects/my-org/my-project/alerts/", params={"limit": 100}
    )


def test_create_project_alert(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test create_project_alert() POSTs new alert."""
    mock_httpx_client.post.return_value = _make_response(
        {
            "id": 42,
            "name": "new-alert",
            "timespanMinutes": 1,
            "quantity": 10,
            "alertRecipients": [],
        }
    )

    alert = ProjectAlert(name="new-alert", timespan_minutes=1, quantity=10)
    created = glitchtip_api.create_project_alert("my-org", "my-project", alert)

    assert created.pk == 42
    assert created.name == "new-alert"
    mock_httpx_client.post.assert_called_once()


def test_create_project_alert_email_recipient_omits_url(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test that email recipients do not send url in the request body."""
    mock_httpx_client.post.return_value = _make_response(
        {
            "id": 42,
            "name": "alert-with-email",
            "timespanMinutes": 1,
            "quantity": 10,
            "alertRecipients": [{"id": 1, "recipientType": "email", "url": ""}],
        }
    )

    alert = ProjectAlert(
        name="alert-with-email",
        timespan_minutes=1,
        quantity=10,
        recipients=[ProjectAlertRecipient(recipient_type=RecipientType.EMAIL)],
    )
    glitchtip_api.create_project_alert("my-org", "my-project", alert)

    mock_httpx_client.post.assert_called_once_with(
        "/api/0/projects/my-org/my-project/alerts/",
        json={
            "name": "alert-with-email",
            "timespanMinutes": 1,
            "quantity": 10,
            "alertRecipients": [{"recipientType": "email"}],
        },
    )


def test_create_project_alert_webhook_recipient_includes_url(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test that webhook recipients include url in the request body."""
    mock_httpx_client.post.return_value = _make_response(
        {
            "id": 42,
            "name": "alert-with-webhook",
            "timespanMinutes": 1,
            "quantity": 10,
            "alertRecipients": [
                {"id": 1, "recipientType": "webhook", "url": "https://example.com/hook"}
            ],
        }
    )

    alert = ProjectAlert(
        name="alert-with-webhook",
        timespan_minutes=1,
        quantity=10,
        recipients=[
            ProjectAlertRecipient(
                recipient_type=RecipientType.WEBHOOK, url="https://example.com/hook"
            )
        ],
    )
    glitchtip_api.create_project_alert("my-org", "my-project", alert)

    mock_httpx_client.post.assert_called_once_with(
        "/api/0/projects/my-org/my-project/alerts/",
        json={
            "name": "alert-with-webhook",
            "timespanMinutes": 1,
            "quantity": 10,
            "alertRecipients": [
                {"recipientType": "webhook", "url": "https://example.com/hook"}
            ],
        },
    )


def test_update_project_alert(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test update_project_alert() PUTs updated alert."""
    mock_httpx_client.put.return_value = _make_response(
        {
            "id": 42,
            "name": "updated-alert",
            "timespanMinutes": 5,
            "quantity": 50,
            "alertRecipients": [],
        }
    )

    alert = ProjectAlert(pk=42, name="updated-alert", timespan_minutes=5, quantity=50)
    updated = glitchtip_api.update_project_alert("my-org", "my-project", alert)

    assert updated.name == "updated-alert"
    mock_httpx_client.put.assert_called_once_with(
        "/api/0/projects/my-org/my-project/alerts/42/",
        json={
            "name": "updated-alert",
            "timespanMinutes": 5,
            "quantity": 50,
            "alertRecipients": [],
        },
    )


def test_update_project_alert_without_pk(glitchtip_api: GlitchtipApi) -> None:
    """Test update_project_alert() raises ValueError without pk."""
    alert = ProjectAlert(name="alert", timespan_minutes=1, quantity=10)
    with pytest.raises(ValueError, match="Cannot update alert without pk"):
        glitchtip_api.update_project_alert("my-org", "my-project", alert)


def test_delete_project_alert(
    glitchtip_api: GlitchtipApi, mock_httpx_client: MagicMock
) -> None:
    """Test delete_project_alert() DELETEs the alert."""
    mock_httpx_client.delete.return_value = MagicMock(spec=httpx.Response)

    glitchtip_api.delete_project_alert("my-org", "my-project", 42)

    mock_httpx_client.delete.assert_called_once_with(
        "/api/0/projects/my-org/my-project/alerts/42/"
    )


def test_context_manager(mock_httpx_client: MagicMock) -> None:
    """Test GlitchtipApi works as context manager."""
    with patch("qontract_utils.glitchtip_api.client.httpx.Client") as mock_cls:
        mock_cls.return_value = mock_httpx_client
        with GlitchtipApi(host="https://glitchtip.example.com", token="token") as api:
            assert api is not None
        mock_httpx_client.close.assert_called_once()


def test_api_call_context() -> None:
    """Test GlitchtipApiCallContext creation."""
    ctx = GlitchtipApiCallContext(
        method="organizations.list", verb="GET", id="https://example.com"
    )
    assert ctx.method == "organizations.list"
    assert ctx.verb == "GET"
    assert ctx.id == "https://example.com"
