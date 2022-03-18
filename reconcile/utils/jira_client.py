from jira import JIRA, Issue
from jira.client import ResultList

from reconcile.utils.secret_reader import SecretReader

from typing import Any, Iterable, Mapping, Optional, Union

GottenIssue = Union[list[dict[str, Any]], ResultList[Issue]]


class JiraClient:
    """Wrapper around Jira client."""

    def __init__(
        self, jira_board: Mapping[str, Any], settings: Optional[Mapping] = None
    ):
        self.secret_reader = SecretReader(settings=settings)
        self.project = jira_board["name"]
        jira_server = jira_board["server"]
        self.server = jira_server["serverUrl"]
        token = jira_server["token"]
        token_auth = self.secret_reader.read(token)
        self.jira = JIRA(self.server, token_auth=token_auth)

    def get_issues(self, fields: Optional[Mapping] = None) -> GottenIssue:
        block_size = 100
        block_num = 0

        all_issues: GottenIssue = []
        jql = "project={}".format(self.project)
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = ",".join(fields)
        while True:
            index = block_num * block_size
            issues = self.jira.search_issues(jql, index, block_size, **kwargs)
            all_issues.extend(issues)
            if len(issues) < block_size:
                break
            block_num += 1

        return all_issues

    def create_issue(
        self,
        summary: str,
        body: str,
        labels: Optional[Iterable[str]] = None,
        links: Iterable[str] = (),
    ) -> Issue:
        """Create an issue in our project with the given labels."""
        issue = self.jira.create_issue(
            project=self.project,
            summary=summary,
            description=body,
            labels=labels,
            issuetype={"name": "Task"},
        )
        for ln in links:
            self.jira.create_issue_link(
                type="is caused by", inwardIssue=issue.key, outwardIssue=ln
            )
        return issue
