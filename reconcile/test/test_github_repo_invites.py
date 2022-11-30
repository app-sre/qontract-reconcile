from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Any
from unittest.mock import MagicMock

import pytest

from reconcile import github_repo_invites
from reconcile.utils.raw_github_api import RawGithubApi


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
                    "url": "https://github.com/org1/project1",
                    "resource": "upstream",
                },
                {
                    "url": "https://github.com/org2/project1",
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
                    "url": "https://github.com/org2/project2",
                    "resource": "upstream",
                }
            ],
        },
    ]
    expected = github_repo_invites.CodeComponents(
        urls=set(
            [
                "https://github.com/org1/project1",
                "https://github.com/org2/project1",
                "https://github.com/org2/project2",
            ]
        ),
        known_orgs=set(
            [
                "https://github.com/org1",
                "https://github.com/org2",
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
    expected_id = "123"
    expected_org = "https://github.com/org1"
    github.repo_invitations.side_effect = [
        [
            {
                "id": expected_id,
                "html_url": f"{expected_org}/project1",
            },
            {
                "id": "456",
                "html_url": "https://github.com/org3/project1",
            },
        ]
    ]
    code_components = github_repo_invites.CodeComponents(
        urls=set([f"{expected_org}/project1"]),
        known_orgs=set([expected_org]),
    )
    dry_run = False
    accepted_invitations = github_repo_invites._accept_invitations(
        github, code_components, dry_run
    )

    github.accept_repo_invitation.assert_called_once_with(expected_id)
    assert accepted_invitations == set([expected_org])


def test_accept_invitations_dry_run(github):
    expected_org = "https://github.com/org1"
    github.repo_invitations.side_effect = [
        [
            {
                "id": "123",
                "html_url": f"{expected_org}/project1",
            },
        ],
    ]
    code_components = github_repo_invites.CodeComponents(
        urls=set([f"{expected_org}/project1"]),
        known_orgs=set([expected_org]),
    )
    dry_run = True
    accepted_invitations = github_repo_invites._accept_invitations(
        github, code_components, dry_run
    )

    github.accept_repo_invitation.assert_not_called()
    assert accepted_invitations == set([expected_org])
