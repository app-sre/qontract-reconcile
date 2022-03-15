from unittest.mock import MagicMock
from reconcile import github_repo_invites
from typing import Any, Iterable, Mapping

from reconcile.utils.raw_github_api import RawGithubApi

import pytest


def test_parse_null_code_components():
    raw_code_components = None
    expected = github_repo_invites.CodeComponents(
        urls=set(),
        known_orgs=set(),
    )
    assert github_repo_invites._parse_code_components(raw_code_components) == expected


def test_parse_valid_code_components():
    raw_code_components: Iterable[Mapping[str, Any]] = [
        {
            "codeComponents": [
                {
                    "url": "org1/project1",
                    "resource": "upstream",
                },
                {
                    "url": "org2/project1",
                    "resource": "upstream",
                },
            ],
        },
        {
            "codeComponents": [],
        },
        {
            "codeComponents": [
                {
                    "url": "org2/project2",
                    "resource": "upstream",
                }
            ],
        },
    ]
    expected = github_repo_invites.CodeComponents(
        urls=set(
            [
                "org1/project1",
                "org2/project1",
                "org2/project2",
            ]
        ),
        known_orgs=set(
            [
                "org1",
                "org2",
            ]
        ),
    )
    assert github_repo_invites._parse_code_components(raw_code_components) == expected


@pytest.fixture
def github():
    mock = MagicMock(spec=RawGithubApi)
    mock.repo_invitations = MagicMock()
    mock.accept_repo_invitation = MagicMock()
    return mock


def test_accept_invitations_no_dry_run(github):
    github.repo_invitations.side_effect = [
        [
            {
                "id": "123",
                "html_url": "org1/project1",
            },
            {
                "id": "456",
                "html_url": "org3/project1",
            },
        ]
    ]
    code_components = github_repo_invites.CodeComponents(
        urls=set(["org1/project1"]),
        known_orgs=set(["org1"]),
    )
    dry_run = False
    accepted_invitations = github_repo_invites._accept_invitations(
        github, code_components, dry_run
    )

    github.accept_repo_invitation.assert_called_once_with("123")
    assert accepted_invitations == set(["org1"])


def test_accept_invitations_dry_run(github):
    github.repo_invitations.side_effect = [
        [
            {
                "id": "123",
                "html_url": "org1/project1",
            },
        ],
    ]
    code_components = github_repo_invites.CodeComponents(
        urls=set(["org1/project1"]),
        known_orgs=set(["org1"]),
    )
    dry_run = True
    accepted_invitations = github_repo_invites._accept_invitations(
        github, code_components, dry_run
    )

    github.accept_repo_invitation.assert_not_called()
    assert accepted_invitations == set(["org1"])
