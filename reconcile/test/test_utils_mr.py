from typing import (
    Any,
    Optional,
)
from unittest import TestCase
from unittest.mock import MagicMock

import pytest
import yaml
from gitlab.exceptions import GitlabError

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import (
    MergeRequestBase,
    MergeRequestProcessingError,
    app_interface_email,
)


class DummyMergeRequest(MergeRequestBase):
    def __init__(self, process_error: Optional[Exception] = None):
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
    diffs: Optional[list] = None,
    create_branch_error: Optional[Exception] = None,
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
