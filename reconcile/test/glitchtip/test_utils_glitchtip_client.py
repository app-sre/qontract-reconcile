import json
from typing import Optional

import httpretty as httpretty_module
import pytest
from reconcile.utils.glitchtip import (
    GlitchtipClient,
    Organization,
    Project,
    Team,
    User,
)
from reconcile.utils.glitchtip.client import get_next_url


@pytest.mark.parametrize(
    "test_input, expected",
    [
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/?limit=1",
                    "rel": "previous",
                    "results": "false",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzEyJTNBMDElM0EwNS4xODYxNjElMkIwMCUzQTAw&limit=1",
                    "rel": "next",
                    "results": "true",
                    "cursor": "cD0yMDIyLTA5LTEzKzEyJTNBMDElM0EwNS4xODYxNjElMkIwMCUzQTAw",
                },
            },
            "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzEyJTNBMDElM0EwNS4xODYxNjElMkIwMCUzQTAw&limit=1",
        ),
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cj0xJnA9MjAyMi0wOS0xMysxMSUzQTIzJTNBMjMuMzA2MTQ4JTJCMDAlM0EwMA%3D%3D&limit=1",
                    "rel": "previous",
                    "results": "true",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw&limit=1",
                    "rel": "next",
                    "results": "true",
                    "cursor": "cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw",
                },
            },
            "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw&limit=1",
        ),
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cj0xJnA9MjAyMi0wOS0xMysxMCUzQTQxJTNBMjQuNDI3ODQxJTJCMDAlM0EwMA%3D%3D&limit=1",
                    "rel": "previous",
                    "results": "true",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/?cursor=cD0yMDIyLTA5LTEzKzExJTNBMjMlM0EyMy4zMDYxNDglMkIwMCUzQTAw&limit=1",
                    "rel": "next",
                    "results": "false",
                },
            },
            None,
        ),
        (
            {
                "previous": {
                    "url": "http://localhost:8000/api/0/organizations/esa/teams/?limit=1",
                    "rel": "previous",
                    "results": "false",
                },
                "next": {
                    "url": "http://localhost:8000/api/0/organizations/esa/teams/?limit=1",
                    "rel": "next",
                    "results": "false",
                },
            },
            None,
        ),
    ],
)
def test_get_next_url(
    test_input: dict[str, dict[str, str]], expected: Optional[str]
) -> None:
    assert get_next_url(test_input) == expected


def test_glitchtip_client_list(
    httpretty: httpretty_module, glitchtip_client: GlitchtipClient, glitchtip_url: str
):
    first_url = f"{glitchtip_url}/data"
    second_url = f"{glitchtip_url}/data2"

    httpretty.register_uri(
        httpretty.GET,
        first_url,
        body=json.dumps([1]),
        content_type="text/json",
        link=f"<{second_url}>; rel='next'; results='true'",
    )
    httpretty.register_uri(
        httpretty.GET,
        second_url,
        body=json.dumps([2]),
        content_type="text/json",
        link=f"<{second_url}>; rel='next'; results='false'",
    )
    assert glitchtip_client._list(first_url) == [1, 2]
    assert httpretty.last_request().headers


def test_glitchtip_client_get(
    httpretty: httpretty_module, glitchtip_client: GlitchtipClient, glitchtip_url: str
):
    url = f"{glitchtip_url}/data"
    test_obj = {"test": "object"}
    httpretty.register_uri(
        httpretty.GET, url, body=json.dumps(test_obj), content_type="text/json"
    )
    assert glitchtip_client._get(url) == test_obj


def test_glitchtip_client_post(
    httpretty: httpretty_module, glitchtip_client: GlitchtipClient, glitchtip_url: str
):
    url = f"{glitchtip_url}/data"
    request_data = {"test": "object"}
    response_data = {"foo": "bar"}

    def request_callback(request, uri, response_headers):
        assert request.headers.get("Content-Type") == "application/json"
        assert json.loads(request.body) == request_data
        return [201, response_headers, json.dumps(response_data)]

    httpretty.register_uri(
        httpretty.POST, url, content_type="text/json", body=request_callback
    )
    assert glitchtip_client._post(url, data=request_data) == response_data


def test_glitchtip_organizations(glitchtip_client: GlitchtipClient):
    assert glitchtip_client.organizations() == [
        Organization(id=10, name="ESA", slug="esa", projects=[], teams=[], users=[]),
        Organization(id=4, name="NASA", slug="nasa", projects=[], teams=[], users=[]),
    ]


def test_glitchtip_create_organization(glitchtip_client: GlitchtipClient):
    org = glitchtip_client.create_organization(name="ASA")
    assert org.name == "ASA"
    assert org.slug == "asa"


def test_glitchtip_delete_organization(glitchtip_client: GlitchtipClient):
    glitchtip_client.delete_organization(slug="esa")


def test_glitchtip_teams(glitchtip_client: GlitchtipClient):
    assert glitchtip_client.teams(organization_slug="nasa") == [
        Team(id=4, slug="nasa-flight-control", users=[]),
        Team(id=2, slug="nasa-pilots", users=[]),
    ]


def test_glitchtip_projects(glitchtip_client: GlitchtipClient):
    assert glitchtip_client.projects(organization_slug="nasa") == [
        Project(
            id=8,
            name="apollo-11-flight-control",
            slug="apollo-11-flight-control",
            platform="python",
            teams=[Team(id=4, slug="nasa-flight-control", users=[])],
        ),
        Project(
            id=7,
            name="apollo-11-spacecraft",
            slug="apollo-11-spacecraft",
            platform="python",
            teams=[
                Team(id=2, slug="nasa-pilots", users=[]),
                Team(id=4, slug="nasa-flight-control", users=[]),
            ],
        ),
    ]


def test_glitchtip_organization_users(glitchtip_client: GlitchtipClient):
    assert glitchtip_client.organization_users(organization_slug="nasa") == [
        User(id=23, email="MichaelCollins@redhat.com", role="member", pending=False),
        User(
            id=22,
            email="GlobalFlightDirector@redhat.com",
            role="owner",
            pending=True,
        ),
        User(id=21, email="BuzzAldrin@redhat.com", role="member", pending=True),
        User(id=20, email="NeilArmstrong@redhat.com", role="member", pending=False),
        User(
            id=5, email="sd-app-sre+glitchtip@redhat.com", role="owner", pending=False
        ),
    ]


def test_glitchtip_team_users(glitchtip_client: GlitchtipClient):
    assert glitchtip_client.team_users(
        organization_slug="nasa", team_slug="nasa-flight-control"
    ) == [
        User(id=23, email="MichaelCollins@redhat.com", role="member", pending=False),
        User(
            id=22,
            email="GlobalFlightDirector@redhat.com",
            role="owner",
            pending=True,
        ),
    ]
