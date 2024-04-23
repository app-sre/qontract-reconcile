from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel
from pytest_httpserver import HTTPServer
from pytest_mock import MockerFixture

from reconcile.glitchtip.reconciler import GlitchtipReconciler
from reconcile.test.fixtures import Fixtures
from reconcile.utils.glitchtip import (
    GlitchtipClient,
    Project,
    Team,
    User,
)
from reconcile.utils.glitchtip.models import Organization


class GlitchtipUrl(BaseModel):
    name: str
    uri: str
    query: str | None = None
    method: str = "POST"
    responses: list[Any] = []


@pytest.fixture
def configure_httpserver(httpserver: HTTPServer) -> Callable[[list[GlitchtipUrl]], int]:
    def f(glitchtip_urls: list[GlitchtipUrl]) -> int:
        i = 0
        for url in glitchtip_urls:
            i += len(url.responses) or 1
            for r in url.responses or [None]:
                req = httpserver.expect_oneshot_request(
                    url.uri,
                    method=url.method,
                    query_string=url.query,
                )
                if r:
                    req.respond_with_json(r)
                else:
                    req.respond_with_data()
        return i

    return f


@pytest.mark.parametrize("dry_run", [True, False])
def test_glitchtip_reconciler_init(
    glitchtip_client_minimal: GlitchtipClient, dry_run: bool
) -> None:
    gtr = GlitchtipReconciler(client=glitchtip_client_minimal, dry_run=dry_run)
    assert gtr.client == glitchtip_client_minimal
    assert gtr.dry_run == dry_run


@pytest.mark.parametrize(
    "fixture_name",
    ["no_current_users", "mixed", "no_desired_users", "change_user_role"],
)
def test_glitchtip_reconciler_reconcile_users(
    fixture_name: str,
    httpserver: HTTPServer,
    glitchtip_client_minimal: GlitchtipClient,
    fx: Fixtures,
    configure_httpserver: Callable[[list[GlitchtipUrl]], int],
) -> None:
    fixture = fx.get_anymarkup(f"reconciler/users/{fixture_name}.yml")
    current_users = [User(**i) for i in fixture["current_users"]]
    desired_users = [User(**i) for i in fixture["desired_users"]]
    expected_return_value = [User(**i) for i in fixture["expected_return_value"]]
    gtr = GlitchtipReconciler(client=glitchtip_client_minimal, dry_run=False)
    request_count = configure_httpserver([
        GlitchtipUrl(**i) for i in fixture["glitchtip_urls"]
    ])

    assert (
        gtr._reconcile_users(
            organization_slug=fixture["organization_slug"],
            current_users=current_users,
            desired_users=desired_users,
        )
        == expected_return_value
    )
    assert len(httpserver.log) == request_count


@pytest.mark.parametrize(
    "fixture_name",
    [
        "no_current_teams",
        "mixed",
        "no_desired_teams",
    ],
)
def test_glitchtip_reconciler_reconcile_teams(
    fixture_name: str,
    httpserver: HTTPServer,
    glitchtip_client_minimal: GlitchtipClient,
    fx: Fixtures,
    configure_httpserver: Callable[[list[GlitchtipUrl]], int],
) -> None:
    fixture = fx.get_anymarkup(f"reconciler/teams/{fixture_name}.yml")
    organization_users = [User(**i) for i in fixture["organization_users"]]
    current_teams = [Team(**i) for i in fixture["current_teams"]]
    desired_teams = [Team(**i) for i in fixture["desired_teams"]]
    expected_return_value = [Team(**i) for i in fixture["expected_return_value"]]
    gtr = GlitchtipReconciler(client=glitchtip_client_minimal, dry_run=False)
    request_count = configure_httpserver([
        GlitchtipUrl(**i) for i in fixture["glitchtip_urls"]
    ])

    assert (
        gtr._reconcile_teams(
            organization_slug=fixture["organization_slug"],
            organization_users=organization_users,
            current_teams=current_teams,
            desired_teams=desired_teams,
        )
        == expected_return_value
    )
    assert len(httpserver.log) == request_count


@pytest.mark.parametrize(
    "fixture_name",
    [
        "mixed",
        "no_current_projects",
        "no_desired_projects",
    ],
)
def test_glitchtip_reconciler_reconcile_projects(
    fixture_name: str,
    httpserver: HTTPServer,
    glitchtip_client_minimal: GlitchtipClient,
    fx: Fixtures,
    configure_httpserver: Callable[[list[GlitchtipUrl]], int],
) -> None:
    fixture = fx.get_anymarkup(f"reconciler/projects/{fixture_name}.yml")
    organization_teams = [Team(**i) for i in fixture["organization_teams"]]
    current_projects = [Project(**i) for i in fixture["current_projects"]]
    desired_projects = [Project(**i) for i in fixture["desired_projects"]]
    expected_return_value = [Project(**i) for i in fixture["expected_return_value"]]
    gtr = GlitchtipReconciler(client=glitchtip_client_minimal, dry_run=False)
    request_count = configure_httpserver([
        GlitchtipUrl(**i) for i in fixture["glitchtip_urls"]
    ])

    assert (
        gtr._reconcile_projects(
            organization_slug=fixture["organization_slug"],
            organization_teams=organization_teams,
            current_projects=current_projects,
            desired_projects=desired_projects,
        )
        == expected_return_value
    )
    assert len(httpserver.log) == request_count


@pytest.mark.parametrize(
    "fixture_name",
    [
        "mixed",
        "no_current_organizations",
        "no_desired_organizations",
    ],
)
def test_glitchtip_reconciler_reconcile_organization(
    fixture_name: str,
    httpserver: HTTPServer,
    glitchtip_client_minimal: GlitchtipClient,
    fx: Fixtures,
    configure_httpserver: Callable[[list[GlitchtipUrl]], int],
    mocker: MockerFixture,
) -> None:
    fixture = fx.get_anymarkup(f"reconciler/organizations/{fixture_name}.yml")
    current_organizations = [
        Organization(**i) for i in fixture["current_organizations"]
    ]
    desired_organizations = [
        Organization(**i) for i in fixture["desired_organizations"]
    ]
    gtr = GlitchtipReconciler(client=glitchtip_client_minimal, dry_run=False)
    reconcile_users_mock = mocker.patch.object(gtr, "_reconcile_users")
    reconcile_teams_mock = mocker.patch.object(gtr, "_reconcile_teams")
    reconcile_projects_mock = mocker.patch.object(gtr, "_reconcile_projects")
    request_count = configure_httpserver([
        GlitchtipUrl(**i) for i in fixture["glitchtip_urls"]
    ])

    gtr.reconcile(
        current=current_organizations,
        desired=desired_organizations,
    )
    assert len(httpserver.log) == request_count
    if desired_organizations:
        assert reconcile_users_mock.called
        assert reconcile_teams_mock.called
        assert reconcile_projects_mock.called
