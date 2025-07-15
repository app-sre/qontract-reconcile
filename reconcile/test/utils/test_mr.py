from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock, patch

import pytest
import yaml
from gitlab.exceptions import GitlabError

import reconcile.typed_queries.smtp
from reconcile.gql_definitions.common.smtp_client_settings import SmtpSettingsV1
from reconcile.gql_definitions.fragments.user import User
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import (
    MergeRequestBase,
    MergeRequestProcessingError,
    app_interface_email,
)
from reconcile.utils.mr.promote_qontract import PromoteQontractReconcileCommercial


class DummyMergeRequest(MergeRequestBase):
    def __init__(self, process_error: Exception | None = None):
        super().__init__()
        self.process_error = process_error

    @property
    def title(self):
        return "xxx"

    @property
    def description(self):
        return "xxx"

    def process(self, gitlab_cli):
        if self.process_error:
            raise self.process_error


def build_gitlab_cli_mock(
    mr_exists: bool = False,
    diffs: list | None = None,
    create_branch_error: Exception | None = None,
) -> GitLabApi:
    cli = MagicMock(spec=GitLabApi)
    cli.mr_exists.return_value = mr_exists
    if create_branch_error:
        cli.create_branch.side_effect = create_branch_error
    cli.project = MagicMock()
    cli.project.mergerequests = MagicMock()
    if diffs is not None:
        cli.project.repository_compare.return_value = {"diffs": diffs}
    return cli


class TestMergeRequestBaseProcessContractTests(TestCase):
    """
    These testcases are here to ensure that
    MergeRequestBase.process() is raises an exception
    when the PR was not opened for a valid reason like
    communication errors, gitlab errors, bugs :)
    """

    @staticmethod
    def test_mr_opened():
        cli = build_gitlab_cli_mock()
        mr = DummyMergeRequest()
        mr.submit_to_gitlab(cli)
        cli.project.mergerequests.create.assert_called()

    def test_cancellation_on_duplicate_mr(self):
        cli = build_gitlab_cli_mock(mr_exists=True)
        mr = DummyMergeRequest()
        mr.submit_to_gitlab(cli)
        self.assertTrue(mr.cancelled)
        cli.project.mergerequests.create.assert_not_called()

    def test_cancellation_on_empty_mr(self):
        cli = build_gitlab_cli_mock(diffs=[])
        mr = DummyMergeRequest()
        mr.submit_to_gitlab(cli)
        self.assertTrue(mr.cancelled)
        cli.project.mergerequests.create.assert_not_called()

    def test_failure_during_branching(self):
        cli = build_gitlab_cli_mock(create_branch_error=GitlabError())
        mr = DummyMergeRequest()
        with self.assertRaises(MergeRequestProcessingError):
            mr.submit_to_gitlab(cli)
        self.assertFalse(cli.project.mergerequests.create.called)

    def test_failure_during_processing(self):
        cli = build_gitlab_cli_mock()
        mr = DummyMergeRequest(process_error=GitlabError())
        with self.assertRaises(MergeRequestProcessingError):
            mr.submit_to_gitlab(cli)
        cli.project.mergerequests.create.assert_not_called()


@pytest.mark.parametrize(
    "aliases, expected_aliases",
    [
        pytest.param(
            {},
            {"aliases": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        pytest.param(
            {"aliases": []},
            {"aliases": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        (
            {"aliases": ["alias1", "alias2"]},
            {"aliases": ["alias1", "alias2"]},
        ),
    ],
)
@pytest.mark.parametrize(
    "users, expected_users",
    [
        pytest.param(
            {},
            {"users": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        pytest.param(
            {"users": []},
            {"users": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        (
            {"users": ["/path/to/user1", "/path/to/user2"]},
            {
                "users": [
                    {"$ref": "/path/to/user1"},
                    {"$ref": "/path/to/user2"},
                ]
            },
        ),
    ],
)
@pytest.mark.parametrize(
    "aws_accounts, expected_aws_accounts",
    [
        pytest.param(
            {},
            {"aws_accounts": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        pytest.param(
            {"aws_accounts": []},
            {"aws_accounts": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        (
            {"aws_accounts": ["/path/to/aws_account1", "/path/to/aws_account2"]},
            {
                "aws_accounts": [
                    {"$ref": "/path/to/aws_account1"},
                    {"$ref": "/path/to/aws_account2"},
                ]
            },
        ),
    ],
)
@pytest.mark.parametrize(
    "services, expected_services",
    [
        pytest.param(
            {},
            {"services": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        pytest.param(
            {"apps": []},
            {"services": []},
            marks=pytest.mark.xfail(strict=True, raises=(KeyError, TypeError)),
        ),
        (
            {"apps": ["/path/to/aws_account1", "/path/to/aws_account2"]},
            {
                "services": [
                    {"$ref": "/path/to/aws_account1"},
                    {"$ref": "/path/to/aws_account2"},
                ]
            },
        ),
    ],
)
def test_email_template(
    aliases: dict[str, Any],
    expected_aliases: dict[str, Any],
    users: dict[str, Any],
    expected_users: dict[str, Any],
    aws_accounts: dict[str, Any],
    expected_aws_accounts: dict[str, Any],
    services: dict[str, Any],
    expected_services: dict[str, Any],
) -> None:
    """Test email template"""

    content = app_interface_email(
        name="test-name",
        subject="test-subject",
        body="test-body",
        **aliases,
        **users,
        **aws_accounts,
        **services,
    )

    email = yaml.safe_load(content)
    email["NAME"] = "test-name"
    email["SUBJECT"] = "test-subject"
    email["BODY"] = "test-body"

    if not aliases and not users and not aws_accounts and not services:
        assert not email["to"]

    for key, value in expected_aliases.items():
        assert email["to"][key] == value
    for key, value in expected_users.items():
        assert email["to"][key] == value
    for key, value in expected_aws_accounts.items():
        assert email["to"][key] == value
    for key, value in expected_services.items():
        assert email["to"][key] == value


def test_process_by_line_search():
    mr = PromoteQontractReconcileCommercial(
        "1q2w3e4", "1q2w3e4r5t6y7u8i9o0p1q2w3e4r5t6y7u8i9o0p"
    )
    content = """
# this is a comment
export IMAGE=abcdefg
"""
    expected = """
# this is a comment
export IMAGE=1q2w3e4
"""
    result = mr._process_by_line_search(
        raw_file=bytes(content, "utf-8"),
        search_text="export IMAGE=",
        replace_text="export IMAGE=1q2w3e4",
    )

    assert expected == result


def test_process_by_json_path():
    mr = PromoteQontractReconcileCommercial(
        "1q2w3e4", "1q2w3e4r5t6y7u8i9o0p1q2w3e4r5t6y7u8i9o0p"
    )
    content = """---
name: saas

resourceTemplates:
- name: qontract-manager
  url: https://github.com/app-sre/qontract-reconcile
  path: /openshift/qontract-manager.yaml
  targets:
  - name: stage
  - name: production
    ref: 82aeb1b1abb6ccb03bc894d9cd3f406fd598d2b3
"""
    expected = """---
name: saas

resourceTemplates:
- name: qontract-manager
  url: https://github.com/app-sre/qontract-reconcile
  path: /openshift/qontract-manager.yaml
  targets:
  - name: stage
  - name: production
    ref: 1q2w3e4r5t6y7u8i9o0p1q2w3e4r5t6y7u8i9o0p
"""

    result = mr._process_by_json_path(
        raw_file=bytes(content, "utf-8"),
        search_text="$.resourceTemplates[?(@.url == 'https://github.com/app-sre/qontract-reconcile')].targets[?(@.name == 'production')].ref",
        replace_text="1q2w3e4r5t6y7u8i9o0p1q2w3e4r5t6y7u8i9o0p",
    )

    assert expected == result


@pytest.fixture
def users():
    return [
        User(
            name="",
            org_username="org_user",
            github_username="github_user",
            pagerduty_username=None,
            tag_on_merge_requests=None,
        )
    ]


@pytest.fixture
def smtp_settings():
    return SmtpSettingsV1(
        mailAddress="redhat.com",
        timeout=30,
        credentials=VaultSecret(path="", field="", version=1, format=""),
    )


def test_author_email_empty(users):
    mr = PromoteQontractReconcileCommercial(
        version="1q2w3e4",
        commit_sha="1q2w3e4r5t6y7u8i9o0p1q2w3e4r5t6y7u8i9o0p",
    )

    assert mr.author_email is None
    assert mr.infer_author(mr.author_email, all_users=users) is None


@patch.object(reconcile.typed_queries.smtp, "settings", autospec=True)
def test_author_org_username(settings, users, smtp_settings):
    mr = PromoteQontractReconcileCommercial(
        version="1q2w3e4",
        commit_sha="1q2w3e4r5t6y7u8i9o0p1q2w3e4r5t6y7u8i9o0p",
        author_email="org_user@redhat.com",
    )
    settings.return_value = smtp_settings

    assert mr.infer_author(author_email=mr.author_email, all_users=users) == "org_user"


@patch.object(reconcile.typed_queries.smtp, "settings", autospec=True)
def test_author_github_username(settings, users, smtp_settings):
    mr = PromoteQontractReconcileCommercial(
        "1q2w3e4",
        "1q2w3e4r5t6y7u8i9o0p1q2w3e4r5t6y7u8i9o0p",
        author_email="github_user@users.noreply.github.com",
    )
    settings.return_value = smtp_settings

    assert mr.infer_author(author_email=mr.author_email, all_users=users) == "org_user"
