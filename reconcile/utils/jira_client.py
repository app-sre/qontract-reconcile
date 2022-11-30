import logging
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import (
    Any,
    Optional,
)

from jira import (
    JIRA,
    Issue,
)
from jira.client import ResultList

from reconcile.utils.secret_reader import SecretReader


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
        read_timeout = 60
        connect_timeout = 60
        if settings and settings["jiraWatcher"]:
            read_timeout = settings["jiraWatcher"]["readTimeout"]
            connect_timeout = settings["jiraWatcher"]["connectTimeout"]

        self.jira = JIRA(
            self.server, token_auth=token_auth, timeout=(read_timeout, connect_timeout)
        )

    def get_issues(self, fields: Optional[Mapping] = None) -> list[Issue]:
        block_size = 100
        block_num = 0

        all_issues: list[Issue] = []
        jql = "project={}".format(self.project)
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = ",".join(fields)
        while True:
            index = block_num * block_size
            issues = self.jira.search_issues(jql, index, block_size, **kwargs)
            if not isinstance(issues, ResultList):
                # if search_issues was executed with json_result=True, then we have a Dict.
                # However, we require a ResultList[Issue].
                # See https://github.com/pycontribs/jira/commit/cc2508485c12232a4a9c4a56ee74175ed818ee20
                logging.warning(
                    "Jira client did not receive a ResultList[Issue]."
                    " Maybe the call was made with json_result=True which is"
                    " currently not supported."
                )
                continue
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
