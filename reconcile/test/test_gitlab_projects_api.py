"""Tests for the gitlab-projects-api client-side integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    GitlabGroupConfig,
    GitlabInstanceConfig,
    GitlabProjectConfig,
    GitlabProjectsTaskResponse,
    GitlabProjectsTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gitlab_projects_api import (
    GitLabProjectsIntegration,
    GitlabProjectsIntegrationParams,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.gitlab_projects.app_code_components import (
    AppCodeComponentsV1,
)
from reconcile.gql_definitions.gitlab_projects.gitlab_instances import (
    GitlabInstanceV1,
    GitlabProjectsV1,
)

SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(GitLabProjectsIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def _make_integration() -> _TestableIntegration:
    return _TestableIntegration(GitlabProjectsIntegrationParams())


def _make_instance(
    name: str = "gitlab-cee",
    url: str = "https://gitlab.cee.redhat.com",
    *,
    ssl_verify: bool | None = None,
    project_requests: list[GitlabProjectsV1] | None = None,
) -> GitlabInstanceV1:
    return GitlabInstanceV1(
        name=name,
        url=url,
        sslVerify=ssl_verify,
        token=VaultSecret(
            path=f"secret/gitlab/{name}/token",
            field="token",
            version=1,
            format=None,
            url=None,
        ),
        projectRequests=project_requests or [],
    )


def _make_code_component(url: str, resource: str = "upstream") -> AppCodeComponentsV1:
    return AppCodeComponentsV1(url=url, resource=resource)


def _groups(instance: GitlabInstanceConfig) -> list[GitlabGroupConfig]:
    return instance.groups or []


def _projects(group: GitlabGroupConfig) -> list[GitlabProjectConfig]:
    return group.projects or []


# ---------------------------------------------------------------------------
# get_gitlab_instances
# ---------------------------------------------------------------------------


def test_get_gitlab_instances_raises_when_empty() -> None:
    query_func = MagicMock(return_value={"instances": []})
    with pytest.raises(IntegrationError, match="no GitLab instances found"):
        GitLabProjectsIntegration.get_gitlab_instances(query_func=query_func)


def test_get_gitlab_instances_returns_all_instances() -> None:
    query_func = MagicMock(
        return_value={
            "instances": [
                {
                    "name": "a",
                    "url": "https://a.example.com",
                    "sslVerify": True,
                    "token": {
                        "path": "p",
                        "field": "f",
                        "version": None,
                        "format": None,
                        "url": None,
                    },
                    "projectRequests": [],
                },
                {
                    "name": "b",
                    "url": "https://b.example.com",
                    "sslVerify": True,
                    "token": {
                        "path": "p",
                        "field": "f",
                        "version": None,
                        "format": None,
                        "url": None,
                    },
                    "projectRequests": [],
                },
            ]
        }
    )
    result = GitLabProjectsIntegration.get_gitlab_instances(query_func=query_func)
    assert [i.name for i in result] == ["a", "b"]


# ---------------------------------------------------------------------------
# get_code_components
# ---------------------------------------------------------------------------


def test_get_code_components_flattens_across_apps() -> None:
    query_func = MagicMock(
        return_value={
            "apps": [
                {"codeComponents": [{"url": "https://x/a/b", "resource": "upstream"}]},
                {"codeComponents": [{"url": "https://x/c/d", "resource": "bundle"}]},
                {"codeComponents": None},
            ]
        }
    )
    result = GitLabProjectsIntegration.get_code_components(query_func=query_func)
    assert [c.url for c in result] == ["https://x/a/b", "https://x/c/d"]


# ---------------------------------------------------------------------------
# filter_requested_projects
# ---------------------------------------------------------------------------


def test_filter_requested_projects_no_filters_passthrough() -> None:
    instances = [
        _make_instance(
            "a", project_requests=[GitlabProjectsV1(group="g", projects=["p1"])]
        )
    ]
    result = GitLabProjectsIntegration.filter_requested_projects(instances, None, None)
    assert (result[0].project_requests or [])[0].projects == ["p1"]


def test_filter_requested_projects_by_instance_name() -> None:
    instances = [_make_instance("a"), _make_instance("b")]
    result = GitLabProjectsIntegration.filter_requested_projects(instances, "a", None)
    assert [i.name for i in result] == ["a"]


def test_filter_requested_projects_by_project_names() -> None:
    instances = [
        _make_instance(
            "a",
            project_requests=[
                GitlabProjectsV1(group="g", projects=["foo", "bar", "baz"])
            ],
        )
    ]
    result = GitLabProjectsIntegration.filter_requested_projects(
        instances, None, frozenset({"foo"})
    )
    assert (result[0].project_requests or [])[0].projects == ["foo"]


def test_filter_requested_projects_drops_empty_group_after_filter() -> None:
    instances = [
        _make_instance(
            "a", project_requests=[GitlabProjectsV1(group="g", projects=["bar"])]
        )
    ]
    result = GitLabProjectsIntegration.filter_requested_projects(
        instances, None, frozenset({"foo"})
    )
    assert result[0].project_requests == []


# ---------------------------------------------------------------------------
# compile_desired_state
# ---------------------------------------------------------------------------


def test_compile_desired_state_valid_project_included() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]

    result = integration.compile_desired_state([instance], code_components)

    assert len(result) == 1
    assert result[0].name == "gitlab-cee"
    group = _groups(result[0])[0]
    assert group.group == "team"
    assert _projects(group)[0].name == "foo"
    assert _projects(group)[0].is_saas_bundle is False


def test_compile_desired_state_missing_code_component_raises() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo", "bar"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]

    with pytest.raises(IntegrationError, match="team/bar"):
        integration.compile_desired_state([instance], code_components)


def test_compile_desired_state_missing_code_component_error_lists_all_missing() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo", "bar"])]
    )

    with pytest.raises(IntegrationError) as exc_info:
        integration.compile_desired_state([instance], code_components=[])

    assert "team/foo" in str(exc_info.value)
    assert "team/bar" in str(exc_info.value)


def test_compile_desired_state_bundle_resource_sets_flag() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [
        _make_code_component("https://gitlab.cee.redhat.com/team/foo", "bundle")
    ]

    result = integration.compile_desired_state([instance], code_components)

    assert _projects(_groups(result[0])[0])[0].is_saas_bundle is True


def test_compile_desired_state_instance_with_only_undeclared_projects_raises() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["undeclared"])]
    )

    with pytest.raises(IntegrationError, match="team/undeclared"):
        integration.compile_desired_state([instance], code_components=[])


def test_compile_desired_state_ssl_verify_none_defaults_true() -> None:
    integration = _make_integration()
    instance = _make_instance(
        ssl_verify=None,
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])],
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]

    result = integration.compile_desired_state([instance], code_components)

    assert result[0].ssl_verify is True


def test_compile_desired_state_token_resolved_as_secret_reference() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]

    result = integration.compile_desired_state([instance], code_components)

    assert result[0].token.secret_manager_url == SECRET_MANAGER_URL
    assert result[0].token.path == "secret/gitlab/gitlab-cee/token"
    assert result[0].token.field == "token"


# ---------------------------------------------------------------------------
# reconcile() — calls API client and returns response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_sends_request_and_returns_response() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]
    instance_config = integration.compile_desired_state([instance], code_components)
    fake_response = GitlabProjectsTaskResponse(
        id="task-123",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/gitlab-projects/reconcile/task-123",
    )

    with patch(
        "reconcile.gitlab_projects_api.gitlab_projects_reconcile",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_reconcile:
        response = await integration.reconcile(instances=instance_config, dry_run=True)

    mock_reconcile.assert_awaited_once()
    called_request = mock_reconcile.call_args[0][0]
    assert called_request.dry_run is True
    assert len(called_request.instances) == 1
    assert response.id == "task-123"


# ---------------------------------------------------------------------------
# async_run() — integration-level orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_run_no_desired_state_exits_early() -> None:
    integration = _make_integration()

    with (
        patch("reconcile.gitlab_projects_api.gql") as mock_gql,
        patch.object(integration, "get_gitlab_instances", return_value=[]),
        patch.object(integration, "get_code_components", return_value=[]),
        patch(
            "reconcile.gitlab_projects_api.gitlab_projects_reconcile",
            new_callable=AsyncMock,
        ) as mock_reconcile,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_async_run_dry_run_polls_and_logs_actions() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]
    fake_response = GitlabProjectsTaskResponse(
        id="task-abc",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/gitlab-projects/reconcile/task-abc",
    )
    fake_result = GitlabProjectsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        applied_actions=[],
        errors=[],
    )

    with (
        patch("reconcile.gitlab_projects_api.gql") as mock_gql,
        patch.object(integration, "get_gitlab_instances", return_value=[instance]),
        patch.object(integration, "get_code_components", return_value=code_components),
        patch(
            "reconcile.gitlab_projects_api.gitlab_projects_reconcile",
            new_callable=AsyncMock,
            return_value=fake_response,
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=fake_result,
        ) as mock_poll,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_awaited_once()
    called_request = mock_reconcile.call_args[0][0]
    assert called_request.dry_run is True
    mock_poll.assert_awaited_once_with(
        status_url=fake_response.status_url,
        result_type=GitlabProjectsTaskResult,
    )


@pytest.mark.asyncio
async def test_async_run_non_dry_run_does_not_poll() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]
    fake_response = GitlabProjectsTaskResponse(
        id="task-xyz",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/gitlab-projects/reconcile/task-xyz",
    )

    with (
        patch("reconcile.gitlab_projects_api.gql") as mock_gql,
        patch.object(integration, "get_gitlab_instances", return_value=[instance]),
        patch.object(integration, "get_code_components", return_value=code_components),
        patch(
            "reconcile.gitlab_projects_api.gitlab_projects_reconcile",
            new_callable=AsyncMock,
            return_value=fake_response,
        ),
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
        ) as mock_poll,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=False)

    mock_poll.assert_not_called()


@pytest.mark.asyncio
async def test_async_run_raises_on_task_result_errors() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]
    fake_response = GitlabProjectsTaskResponse(
        id="task-err",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/gitlab-projects/reconcile/task-err",
    )
    fake_result = GitlabProjectsTaskResult(
        status=TaskStatus.FAILED,
        actions=[],
        applied_count=0,
        applied_actions=[],
        errors=["gitlab-cee/team: boom"],
    )

    with (
        patch("reconcile.gitlab_projects_api.gql") as mock_gql,
        patch.object(integration, "get_gitlab_instances", return_value=[instance]),
        patch.object(integration, "get_code_components", return_value=code_components),
        patch(
            "reconcile.gitlab_projects_api.gitlab_projects_reconcile",
            new_callable=AsyncMock,
            return_value=fake_response,
        ),
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=fake_result,
        ),
    ):
        mock_gql.get_api.return_value = MagicMock()
        with pytest.raises(IntegrationError, match="boom"):
            await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_async_run_raises_on_pending_timeout() -> None:
    integration = _make_integration()
    instance = _make_instance(
        project_requests=[GitlabProjectsV1(group="team", projects=["foo"])]
    )
    code_components = [_make_code_component("https://gitlab.cee.redhat.com/team/foo")]
    fake_response = GitlabProjectsTaskResponse(
        id="task-pending",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/gitlab-projects/reconcile/task-pending",
    )
    fake_result = GitlabProjectsTaskResult(status=TaskStatus.PENDING)

    with (
        patch("reconcile.gitlab_projects_api.gql") as mock_gql,
        patch.object(integration, "get_gitlab_instances", return_value=[instance]),
        patch.object(integration, "get_code_components", return_value=code_components),
        patch(
            "reconcile.gitlab_projects_api.gitlab_projects_reconcile",
            new_callable=AsyncMock,
            return_value=fake_response,
        ),
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=fake_result,
        ),
    ):
        mock_gql.get_api.return_value = MagicMock()
        with pytest.raises(IntegrationError, match="did not complete"):
            await integration.async_run(dry_run=True)
