from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock

from gitlab.exceptions import GitlabError

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import (
    MergeRequestBase,
    MergeRequestProcessingError,
)


class DummyMergeRequest(MergeRequestBase):
    def __init__(self, process_error: Optional[Exception] = None):
        super().__init__()
        self.process_error = process_error

    def title(self):
        return "xxx"

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
