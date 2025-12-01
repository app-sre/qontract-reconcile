from __future__ import annotations

import functools
import logging
from typing import (
    TYPE_CHECKING,
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

if TYPE_CHECKING:
    from collections.abc import Iterable


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


CREATE_ISSUES = "CREATE_ISSUES"
TRANSITION_ISSUES = "TRANSITION_ISSUES"
PERMISSIONS = [CREATE_ISSUES, TRANSITION_ISSUES]


class JiraClient:
    """Wrapper around Jira client."""

    DEFAULT_CONNECT_TIMEOUT = 60
    DEFAULT_READ_TIMEOUT = 60

    def __init__(self, jira_api: JIRA, project: str, server: str):
        self.server = server
        self.project = project
        self.jira = jira_api

        # some caches
        self.priorities = functools.lru_cache(maxsize=None)(self._priorities)
        self.public_projects = functools.lru_cache(maxsize=None)(self._public_projects)
        self.my_permissions = functools.lru_cache(maxsize=None)(self._my_permissions)
        self.project_issue_types = functools.cache(self._project_issue_types)
        self.project_issue_fields = functools.cache(self._project_issue_fields)

    @staticmethod
    def create(
        project_name: str,
        token: str,
        email: str | None,
        server_url: str,
        jira_watcher_settings: JiraWatcherSettings | None = None,
    ) -> JiraClient:
        """Create a Jira client for the given project."""
        read_timeout = JiraClient.DEFAULT_READ_TIMEOUT
        connect_timeout = JiraClient.DEFAULT_CONNECT_TIMEOUT
        if jira_watcher_settings:
            read_timeout = jira_watcher_settings.read_timeout
            connect_timeout = jira_watcher_settings.connect_timeout

        # Jira Cloud uses email+API token for basic auth
        # Jira Server/Data Center can use token auth (personal access token)
        auth_params: dict[str, Any] = (
            {"basic_auth": (email, token)} if email else {"token_auth": token}
        )
        jira_api = JIRA(
            server=server_url,
            timeout=(read_timeout, connect_timeout),
            logging=False,
            **auth_params,
        )
        return JiraClient(
            jira_api=jira_api,
            project=project_name,
            server=server_url,
        )

    @property
    def is_cloud(self) -> bool:
        """Return whether we are on a Cloud based Jira instance."""
        return self.jira.deploymentType == "Cloud"

    def get_issues(self, fields: Iterable | None = None) -> list[Issue]:
        """Return all issues for our project."""
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
        """Return my permissions for the given project.

        Don't use this function directly, use self.my_permissions which is cached."""
        if self.is_cloud:
            return self.jira.my_permissions(
                projectKey=project, permissions=",".join(PERMISSIONS)
            )["permissions"]
        return self.jira.my_permissions(projectKey=project)["permissions"]

    def can_i(self, permission: str) -> bool:
        """Return whether I have the given permission in the project."""
        return bool(
            self.my_permissions(project=self.project)[permission]["havePermission"]
        )

    def can_create_issues(self) -> bool:
        """Return whether I can create issues in the project."""
        return self.can_i(CREATE_ISSUES)

    def can_transition_issues(self) -> bool:
        """Return whether I can transition issues in the project."""
        return self.can_i(TRANSITION_ISSUES)

    def _project_issue_types(self, project: str) -> list[IssueType]:
        """Return all available issue types (e.g. Task, Bug) for the project.

        Don't use this function directly, use self.project_issue_types which is cached.
        """
        # Don't use self.project here, because of function.cache usage
        return [
            IssueType(id=t.id, name=t.name, statuses=[s.name for s in t.statuses])
            for t in self.jira.issue_types_for_project(project)
        ]

    def get_issue_type(self, issue_type: str) -> IssueType | None:
        """Return a issue type (e.g. Task) for the project if it exists."""
        for _issue_type in self.project_issue_types(self.project):
            if _issue_type.name == issue_type:
                return _issue_type
        return None

    @staticmethod
    def _get_allowed_issue_field_options(
        allowed_values: list[Resource] | list[dict[str, str]],
    ) -> list[FieldOption | CustomFieldOption]:
        """Return a list of allowed values for a field. E.g. Minor, Major ... for Priority in a Task."""
        items: list[FieldOption | CustomFieldOption] = []
        for v in allowed_values:
            match v:
                case dict() if "value" in v:
                    items.append(CustomFieldOption(value=v["value"]))
                case dict() if "name" in v:
                    items.append(FieldOption(name=v["name"]))
                case JiraCustomFieldOption():
                    items.append(CustomFieldOption(value=v.value))
                case Resource():
                    items.append(FieldOption(name=v.name))
                case _:
                    logging.warning(f"Unknown allowed value type: {type(v)}")
        return items

    def _project_issue_fields(
        self, project: str, issue_type_id: str
    ) -> list[IssueField]:
        """Return all available issue fields for the project.

        This API endpoint needs createIssue project permissions.
        """
        # Don't use self.project here, because of function.cache usage
        if self.is_cloud:
            metadata = self.jira.createmeta(
                projectKeys=self.project,
                issuetypeIds=[issue_type_id],
                expand="projects.issuetypes.fields",
            )
            if not metadata["projects"] or not metadata["projects"][0]["issuetypes"]:
                return []
            return [
                IssueField(
                    name=field["name"],
                    id=field_id,
                    options=self._get_allowed_issue_field_options(
                        field.get("allowedValues", [])
                    ),
                )
                for field_id, field in metadata["projects"][0]["issuetypes"][0][
                    "fields"
                ].items()
            ]

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
        if self.is_cloud:
            # Cloud does not have a way to retrieve project specific priority schemes
            return []

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
        """Return whether the project is archived."""
        return getattr(self.jira.project(self.project), "archived", False)
