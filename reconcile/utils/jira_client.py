from __future__ import annotations

import logging
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import (
    Any,
    Optional,
    Protocol,
)

from jira import (
    JIRA,
    Issue,
)
from jira.client import ResultList
from pydantic import BaseModel

from reconcile.utils.secret_reader import SecretReader


class JiraWatcherSettings(Protocol):
    read_timeout: int
    connect_timeout: int


class SecurityLevel(BaseModel):
    """Jira security level."""

    id: str
    name: str


class Priority(BaseModel):
    """Jira priority."""

    id: str
    name: str


class IssueType(BaseModel):
    """Jira issue type."""

    id: str
    name: str
    statuses: list[str]


class JiraClient:
    """Wrapper around Jira client."""

    DEFAULT_CONNECT_TIMEOUT = 60
    DEFAULT_READ_TIMEOUT = 60

    def __init__(
        self,
        jira_board: Optional[Mapping[str, Any]] = None,
        settings: Optional[Mapping] = None,
        jira_api: Optional[JIRA] = None,
        project: Optional[str] = None,
        server: Optional[str] = None,
    ):
        """
        Note: jira_board and settings is to be deprecated. Use JiraClient.create() instead.
        """
        if jira_api and jira_board:
            raise RuntimeError(
                "jira_board parameter is deprecated. Use JiraClient.create() instead."
            )
        if not (jira_api and project):
            # kept for backwards-compatibility
            if not jira_board:
                raise RuntimeError(
                    "JiraClient needs jira_api and project or jira_board."
                )
            self._deprecated_init(jira_board=jira_board, settings=settings)
            return

        self.server = server
        self.project = project
        self.jira = jira_api

    def _deprecated_init(
        self, jira_board: Mapping[str, Any], settings: Optional[Mapping]
    ) -> None:
        secret_reader = SecretReader(settings=settings)
        self.project = jira_board["name"]
        jira_server = jira_board["server"]
        self.server = jira_server["serverUrl"]
        token = jira_server["token"]
        token_auth = secret_reader.read(token)
        read_timeout = 60
        connect_timeout = 60
        if settings and settings["jiraWatcher"]:
            read_timeout = settings["jiraWatcher"]["readTimeout"]
            connect_timeout = settings["jiraWatcher"]["connectTimeout"]
        if not self.server:
            raise RuntimeError("JiraClient.server is not set.")

        self.jira = JIRA(
            self.server,
            token_auth=token_auth,
            timeout=(read_timeout, connect_timeout),
        )

    @staticmethod
    def create(
        project_name: str,
        token: str,
        server_url: str,
        jira_watcher_settings: Optional[JiraWatcherSettings] = None,
    ) -> JiraClient:
        read_timeout = JiraClient.DEFAULT_READ_TIMEOUT
        connect_timeout = JiraClient.DEFAULT_CONNECT_TIMEOUT
        if jira_watcher_settings:
            read_timeout = jira_watcher_settings.read_timeout
            connect_timeout = jira_watcher_settings.connect_timeout
        jira_api = JIRA(
            server=server_url, token_auth=token, timeout=(read_timeout, connect_timeout)
        )
        return JiraClient(
            jira_api=jira_api,
            project=project_name,
            server=server_url,
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

    def can_i(self, permission: str) -> bool:
        return bool(
            self.jira.my_permissions(projectKey=self.project)["permissions"][
                permission
            ]["havePermission"]
        )

    def can_create_issues(self) -> bool:
        return self.can_i("CREATE_ISSUES")

    def can_transition_issues(self) -> bool:
        return self.can_i("TRANSITION_ISSUES")

    def project_issue_types(self, project: str) -> list[IssueType]:
        return [
            IssueType(id=t.id, name=t.name, statuses=[s.name for s in t.statuses])
            for t in self.jira.issue_types_for_project(project)
        ]

    def security_levels(self) -> list[SecurityLevel]:
        """Return a list of all available security levels for the project.

        This API endpoint needs admin/owner project permissions.
        """
        scheme = self.jira.project_issue_security_level_scheme(self.project)
        return [SecurityLevel(id=level.id, name=level.name) for level in scheme.levels]

    def priorities(self) -> list[Priority]:
        """Return a list of all available Jira priorities."""
        return [Priority(id=p.id, name=p.name) for p in self.jira.priorities()]

    def project_priority_scheme(self) -> list[str]:
        """Return a list of all priority IDs for the project."""
        scheme = self.jira.project_priority_scheme(self.project)
        return scheme.optionIds

    def public_projects(self) -> list[str]:
        """Return a list of all public available projects."""
        if not self.server:
            raise RuntimeError("JiraClient.server is not set.")

        # use anonymous access to get public projects
        jira_api_anon = JIRA(server=self.server)
        return [project.key for project in jira_api_anon.projects()]
