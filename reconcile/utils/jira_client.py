from __future__ import annotations

import functools
import logging
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import (
    Any,
    Protocol,
)

from jira import (
    JIRA,
    Issue,
)
from jira.client import ResultList
from jira.resources import CustomFieldOption as JiraCustomFieldOption
from jira.resources import Resource
from pydantic import BaseModel

from reconcile.utils.secret_reader import SecretReader


class JiraWatcherSettings(Protocol):
    read_timeout: int
    connect_timeout: int


class Priority(BaseModel):
    """Jira priority."""

    id: str
    name: str


class IssueType(BaseModel):
    """Jira issue type."""

    id: str
    name: str
    statuses: list[str]


class FieldOption(BaseModel):
    """A standard buildin issue field option."""

    name: str

    def __eq__(self, value: Any) -> bool:
        """Compare the field option with a string value."""
        if isinstance(value, str):
            return self.name == value
        return False

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.__str__()


class CustomFieldOption(BaseModel):
    """A custom issue field option."""

    value: str

    def __eq__(self, value: Any) -> bool:
        """Compare the custom field option with a string value."""
        if isinstance(value, str):
            return self.value == value
        return False

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.__str__()


class IssueField(BaseModel):
    """Jira issue field."""

    id: str
    name: str
    options: list[FieldOption | CustomFieldOption]


class JiraClient:
    """Wrapper around Jira client."""

    DEFAULT_CONNECT_TIMEOUT = 60
    DEFAULT_READ_TIMEOUT = 60

    def __init__(
        self,
        jira_board: Mapping[str, Any] | None = None,
        settings: Mapping | None = None,
        jira_api: JIRA | None = None,
        project: str | None = None,
        server: str | None = None,
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

        # some caches
        self.priorities = functools.lru_cache(maxsize=None)(self._priorities)
        self.public_projects = functools.lru_cache(maxsize=None)(self._public_projects)
        self.my_permissions = functools.lru_cache(maxsize=None)(self._my_permissions)
        self.project_issue_types = functools.cache(self._project_issue_types)
        self.project_issue_fields = functools.cache(self._project_issue_fields)

    def _deprecated_init(
        self, jira_board: Mapping[str, Any], settings: Mapping | None
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
            logging=False,
        )

    @staticmethod
    def create(
        project_name: str,
        token: str,
        server_url: str,
        jira_watcher_settings: JiraWatcherSettings | None = None,
    ) -> JiraClient:
        read_timeout = JiraClient.DEFAULT_READ_TIMEOUT
        connect_timeout = JiraClient.DEFAULT_CONNECT_TIMEOUT
        if jira_watcher_settings:
            read_timeout = jira_watcher_settings.read_timeout
            connect_timeout = jira_watcher_settings.connect_timeout
        jira_api = JIRA(
            server=server_url,
            token_auth=token,
            timeout=(read_timeout, connect_timeout),
            logging=False,
        )
        return JiraClient(
            jira_api=jira_api,
            project=project_name,
            server=server_url,
        )

    def get_issues(self, fields: Mapping | None = None) -> list[Issue]:
        block_size = 100
        block_num = 0

        all_issues: list[Issue] = []
        jql = f"project={self.project}"
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
        labels: Iterable[str] | None = None,
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

    def _my_permissions(self, project: str) -> dict[str, Any]:
        return self.jira.my_permissions(projectKey=project)["permissions"]

    def can_i(self, permission: str) -> bool:
        return bool(
            self.my_permissions(project=self.project)[permission]["havePermission"]
        )

    def can_create_issues(self) -> bool:
        return self.can_i("CREATE_ISSUES")

    def can_transition_issues(self) -> bool:
        return self.can_i("TRANSITION_ISSUES")

    def _project_issue_types(self, project: str) -> list[IssueType]:
        # Don't use self.project here, because of function.cache usage
        return [
            IssueType(id=t.id, name=t.name, statuses=[s.name for s in t.statuses])
            for t in self.jira.issue_types_for_project(project)
        ]

    def get_issue_type(self, issue_type: str) -> IssueType | None:
        for _issue_type in self.project_issue_types(self.project):
            if _issue_type.name == issue_type:
                return _issue_type
        return None

    @staticmethod
    def _get_allowed_issue_field_options(
        allowed_values: list[Resource],
    ) -> list[FieldOption | CustomFieldOption]:
        """Return a list of allowed values for a field."""
        return [
            CustomFieldOption(value=v.value)
            if isinstance(v, JiraCustomFieldOption)
            else FieldOption(name=v.name)
            for v in allowed_values
        ]

    def _project_issue_fields(
        self, project: str, issue_type_id: str
    ) -> list[IssueField]:
        """Return all available issue fields for the project.

        This API endpoint needs createIssue project permissions.
        """
        # Don't use self.project here, because of function.cache usage
        return [
            IssueField(
                name=field.name,
                id=field.fieldId,
                options=self._get_allowed_issue_field_options(
                    getattr(field, "allowedValues", [])
                ),
            )
            for field in self.jira.project_issue_fields(
                project=project, issue_type=issue_type_id, maxResults=9999
            )
        ]

    def project_issue_field(self, issue_type_id: str, field: str) -> IssueField | None:
        """Return a issue field for the project if it exists.

        This API endpoint needs createIssue project permissions.
        """
        for _field in self.project_issue_fields(
            project=self.project, issue_type_id=issue_type_id
        ):
            if _field.name == field:
                return _field
        return None

    def _priorities(self) -> list[Priority]:
        """Return a list of all available Jira priorities."""
        return [Priority(id=p.id, name=p.name) for p in self.jira.priorities()]

    def project_priority_scheme(self) -> list[str]:
        """Return a list of all priority IDs for the project."""
        scheme = self.jira.project_priority_scheme(self.project)
        return scheme.optionIds

    def _public_projects(self) -> list[str]:
        """Return a list of all public available projects."""
        if not self.server:
            raise RuntimeError("JiraClient.server is not set.")

        # use anonymous access to get public projects
        jira_api_anon = JIRA(
            server=self.server,
            timeout=(
                JiraClient.DEFAULT_READ_TIMEOUT,
                JiraClient.DEFAULT_CONNECT_TIMEOUT,
            ),
            logging=False,
        )
        return [project.key for project in jira_api_anon.projects()]

    def components(self) -> list[str]:
        """Return a list of all components for the project."""
        return [c.name for c in self.jira.project_components(self.project)]

    @property
    def is_archived(self) -> bool:
        return self.jira.project(self.project).archived
