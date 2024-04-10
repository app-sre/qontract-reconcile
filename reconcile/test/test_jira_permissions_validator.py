from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import Mock

import pytest
from jira import JIRAError
from pytest_mock import MockerFixture

from reconcile.gql_definitions.jira_permissions_validator.jira_boards_for_permissions_validator import (
    JiraBoardV1,
)
from reconcile.jira_permissions_validator import (
    ValidationError,
    board_is_valid,
    get_jira_boards,
    validate_boards,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils import metrics
from reconcile.utils.jira_client import IssueType, JiraClient, SecurityLevel


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("jira_permissions_validator")


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("boards.yml")


@pytest.fixture
def query_func(
    data_factory: Callable[[type[JiraBoardV1], Mapping[str, Any]], Mapping[str, Any]],
    raw_fixture_data: dict[str, Any],
) -> Callable:
    return lambda *args, **kwargs: {
        "jira_boards": [
            data_factory(JiraBoardV1, item) for item in raw_fixture_data["jira_boards"]
        ]
    }


@pytest.fixture
def boards(query_func: Callable) -> list[JiraBoardV1]:
    return get_jira_boards(query_func)


def test_jira_permissions_validator_get_jira_boards(
    query_func: Callable, gql_class_factory: Callable
) -> None:
    default = {
        "name": "jira-board-default",
        "server": {
            "serverUrl": "https://jira-server.com",
            "token": {"path": "vault/path/token", "field": "token"},
        },
        "issueResolveState": "Closed",
        "severityPriorityMappings": {
            "name": "major-major",
            "mappings": [
                {"priority": "Minor"},
                {"priority": "Major"},
                {"priority": "Critical"},
            ],
        },
    }
    custom = {
        "name": "jira-board-custom",
        "server": {
            "serverUrl": "https://jira-server.com",
            "token": {"path": "vault/path/token", "field": "token"},
        },
        "issueType": "bug",
        "issueResolveState": "Closed",
        "issueReopenState": "Open",
        "issueSecurityId": 32168,
        "severityPriorityMappings": {
            "name": "major-major",
            "mappings": [
                {"priority": "Minor"},
                {"priority": "Major"},
                {"priority": "Major"},
                {"priority": "Critical"},
            ],
        },
    }
    assert get_jira_boards(query_func) == [
        gql_class_factory(JiraBoardV1, default),
        gql_class_factory(JiraBoardV1, custom),
    ]


@pytest.mark.parametrize(
    "board_is_valid, exit_on_permission_errors, error_returned, metric_set",
    [
        (0, True, False, False),
        (ValidationError.CANT_CREATE_ISSUE, True, True, False),
        (ValidationError.CANT_TRANSITION_ISSUES, True, True, False),
        (ValidationError.INVALID_ISSUE_TYPE, True, True, False),
        (ValidationError.INVALID_ISSUE_STATE, True, True, False),
        (ValidationError.INVALID_SECURITY_LEVEL, True, True, False),
        (ValidationError.INVALID_PRIORITY, True, True, False),
        (ValidationError.PUBLIC_PROJECT_NO_SECURITY_LEVEL, True, True, False),
        (ValidationError.PERMISSION_ERROR, True, True, True),
        # special case: CANT_CREATE_ISSUE and PERMISSION_ERROR
        (
            ValidationError.CANT_CREATE_ISSUE | ValidationError.PERMISSION_ERROR,
            True,
            True,
            False,
        ),
        (
            ValidationError.CANT_CREATE_ISSUE | ValidationError.PERMISSION_ERROR,
            False,
            True,
            False,
        ),
        # test with another error
        (
            ValidationError.INVALID_PRIORITY | ValidationError.PERMISSION_ERROR,
            True,
            True,
            False,
        ),
        (
            ValidationError.INVALID_PRIORITY | ValidationError.PERMISSION_ERROR,
            False,
            True,
            False,
        ),
    ],
)
def test_jira_permissions_validator_validate_boards(
    mocker: MockerFixture,
    boards: list[JiraBoardV1],
    secret_reader: Mock,
    board_is_valid: ValidationError,
    exit_on_permission_errors: bool,
    error_returned: bool,
    metric_set: bool,
) -> None:
    board_is_valid_mock = mocker.patch(
        "reconcile.jira_permissions_validator.board_is_valid"
    )
    board_is_valid_mock.return_value = board_is_valid
    metrics_container_mock = mocker.create_autospec(spec=metrics.MetricsContainer)
    jira_client_class = mocker.create_autospec(spec=JiraClient)
    assert (
        validate_boards(
            metrics_container=metrics_container_mock,
            secret_reader=secret_reader,
            exit_on_permission_errors=exit_on_permission_errors,
            jira_client_settings=None,
            jira_boards=boards,
            default_issue_type="task",
            default_reopen_state="new",
            jira_client_class=jira_client_class,
        )
        == error_returned
    )
    if metric_set:
        metrics_container_mock.set_gauge.assert_called()
    else:
        metrics_container_mock.set_gauge.assert_not_called()


def test_jira_permissions_validator_board_is_valid_happy_path(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    board = gql_class_factory(
        JiraBoardV1,
        {
            "name": "jira-board-default",
            "server": {
                "serverUrl": "https://jira-server.com",
                "token": {"path": "vault/path/token", "field": "token"},
            },
            "issueType": "bug",
            "issueResolveState": "Closed",
            "issueReopenState": "Open",
            "issueSecurityId": "32168",
            "severityPriorityMappings": {
                "name": "major-major",
                "mappings": [
                    {"priority": "Minor"},
                    {"priority": "Major"},
                    {"priority": "Critical"},
                ],
            },
        },
    )
    jira_client = mocker.create_autospec(spec=JiraClient)
    jira_client.can_create_issues.return_value = True
    jira_client.can_transition_issues.return_value = True
    jira_client.project_issue_types.return_value = [
        IssueType(id="1", name="task", statuses=["open", "closed"]),
        IssueType(id="2", name="bug", statuses=["open", "closed"]),
    ]
    jira_client.security_levels.return_value = [
        SecurityLevel(id="32168", name="foo"),
        SecurityLevel(id="1", name="bar"),
    ]
    jira_client.project_priority_scheme.return_value = ["1", "2", "3"]
    assert board_is_valid(
        jira=jira_client,
        board=board,
        default_issue_type="task",
        default_reopen_state="new",
        jira_server_priorities={"Minor": "1", "Major": "2", "Critical": "3"},
        public_projects=[],
    ) == ValidationError(0)


def test_jira_permissions_validator_board_is_valid_all_errors(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    board = gql_class_factory(
        JiraBoardV1,
        {
            "name": "jira-board-default",
            "server": {
                "serverUrl": "https://jira-server.com",
                "token": {"path": "vault/path/token", "field": "token"},
            },
            "issueType": "bug",
            "issueResolveState": "Closed",
            "issueReopenState": "Open",
            "issueSecurityId": "32168",
            "severityPriorityMappings": {
                "name": "major-major",
                "mappings": [
                    {"priority": "Minor"},
                    {"priority": "Major"},
                    {"priority": "Critical"},
                ],
            },
        },
    )
    jira_client = mocker.create_autospec(spec=JiraClient)
    jira_client.can_create_issues.return_value = False
    jira_client.can_transition_issues.return_value = False
    jira_client.project_issue_types.return_value = []
    jira_client.security_levels.return_value = [
        SecurityLevel(id="1", name="bar"),
    ]
    jira_client.project_priority_scheme.return_value = ["1", "2"]
    assert (
        board_is_valid(
            jira=jira_client,
            board=board,
            default_issue_type="task",
            default_reopen_state="new",
            jira_server_priorities={"Minor": "1", "Major": "2", "Critical": "3"},
            public_projects=[],
        )
        == ValidationError.CANT_CREATE_ISSUE
        | ValidationError.CANT_TRANSITION_ISSUES
        | ValidationError.INVALID_ISSUE_TYPE
        | ValidationError.INVALID_ISSUE_STATE
        | ValidationError.INVALID_SECURITY_LEVEL
        | ValidationError.INVALID_PRIORITY
    )


def test_jira_permissions_validator_board_is_valid_bad_issue_status(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    board = gql_class_factory(
        JiraBoardV1,
        {
            "name": "jira-board-default",
            "server": {
                "serverUrl": "https://jira-server.com",
                "token": {"path": "vault/path/token", "field": "token"},
            },
            "issueType": "bug",
            "issueResolveState": "Closed",
            "issueReopenState": "Open",
            "issueSecurityId": "32168",
            "severityPriorityMappings": {
                "name": "major-major",
                "mappings": [
                    {"priority": "Minor"},
                    {"priority": "Major"},
                    {"priority": "Critical"},
                ],
            },
        },
    )
    jira_client = mocker.create_autospec(spec=JiraClient)
    jira_client.can_create_issues.return_value = True
    jira_client.can_transition_issues.return_value = True
    jira_client.project_issue_types.return_value = [
        IssueType(id="1", name="task", statuses=["not - open", "closed"]),
        IssueType(id="2", name="bug", statuses=["not - open", "closed"]),
    ]
    jira_client.security_levels.return_value = [
        SecurityLevel(id="32168", name="foo"),
        SecurityLevel(id="1", name="bar"),
    ]
    jira_client.project_priority_scheme.return_value = ["1", "2", "3"]
    assert (
        board_is_valid(
            jira=jira_client,
            board=board,
            default_issue_type="task",
            default_reopen_state="new",
            jira_server_priorities={"Minor": "1", "Major": "2", "Critical": "3"},
            public_projects=[],
        )
        == ValidationError.INVALID_ISSUE_STATE
    )


def test_jira_permissions_validator_board_is_valid_public_project(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    board = gql_class_factory(
        JiraBoardV1,
        {
            "name": "jira-board-default",
            "server": {
                "serverUrl": "https://jira-server.com",
                "token": {"path": "vault/path/token", "field": "token"},
            },
            "issueType": "bug",
            "issueResolveState": "Closed",
            "issueReopenState": "Open",
            "issueSecurityId": None,
            "severityPriorityMappings": {
                "name": "major-major",
                "mappings": [
                    {"priority": "Minor"},
                    {"priority": "Major"},
                    {"priority": "Critical"},
                ],
            },
        },
    )
    jira_client = mocker.create_autospec(spec=JiraClient)
    jira_client.can_create_issues.return_value = True
    jira_client.can_transition_issues.return_value = True
    jira_client.project_issue_types.return_value = [
        IssueType(id="1", name="task", statuses=["open", "closed"]),
        IssueType(id="2", name="bug", statuses=["open", "closed"]),
    ]
    jira_client.security_levels.return_value = [
        SecurityLevel(id="32168", name="foo"),
        SecurityLevel(id="1", name="bar"),
    ]
    jira_client.project_priority_scheme.return_value = ["1", "2", "3"]
    assert (
        board_is_valid(
            jira=jira_client,
            board=board,
            default_issue_type="task",
            default_reopen_state="new",
            jira_server_priorities={"Minor": "1", "Major": "2", "Critical": "3"},
            public_projects=["jira-board-default"],
        )
        == ValidationError.PUBLIC_PROJECT_NO_SECURITY_LEVEL
    )


def test_jira_permissions_validator_board_is_valid_permission_error(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    board = gql_class_factory(
        JiraBoardV1,
        {
            "name": "jira-board-default",
            "server": {
                "serverUrl": "https://jira-server.com",
                "token": {"path": "vault/path/token", "field": "token"},
            },
            "issueType": "bug",
            "issueResolveState": "Closed",
            "issueReopenState": "Open",
            "issueSecurityId": "32168",
            "severityPriorityMappings": {
                "name": "major-major",
                "mappings": [
                    {"priority": "Minor"},
                    {"priority": "Major"},
                    {"priority": "Critical"},
                ],
            },
        },
    )
    jira_client = mocker.create_autospec(spec=JiraClient)
    jira_client.can_create_issues.side_effect = JIRAError(status_code=403)
    assert (
        board_is_valid(
            jira=jira_client,
            board=board,
            default_issue_type="task",
            default_reopen_state="new",
            jira_server_priorities={"Minor": "1", "Major": "2", "Critical": "3"},
            public_projects=[],
        )
        == ValidationError.PERMISSION_ERROR
    )


def test_jira_permissions_validator_board_is_valid_exception(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    board = gql_class_factory(
        JiraBoardV1,
        {
            "name": "jira-board-default",
            "server": {
                "serverUrl": "https://jira-server.com",
                "token": {"path": "vault/path/token", "field": "token"},
            },
            "issueType": "bug",
            "issueResolveState": "Closed",
            "issueReopenState": "Open",
            "issueSecurityId": "32168",
            "severityPriorityMappings": {
                "name": "major-major",
                "mappings": [
                    {"priority": "Minor"},
                    {"priority": "Major"},
                    {"priority": "Critical"},
                ],
            },
        },
    )
    jira_client = mocker.create_autospec(spec=JiraClient)
    jira_client.can_create_issues.side_effect = JIRAError(status_code=500)
    with pytest.raises(JIRAError):
        board_is_valid(
            jira=jira_client,
            board=board,
            default_issue_type="task",
            default_reopen_state="new",
            jira_server_priorities={"Minor": "1", "Major": "2", "Critical": "3"},
            public_projects=[],
        )


def test_jira_permissions_validator_board_is_valid_exception_401(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    board = gql_class_factory(
        JiraBoardV1,
        {
            "name": "jira-board-default",
            "server": {
                "serverUrl": "https://jira-server.com",
                "token": {"path": "vault/path/token", "field": "token"},
            },
            "issueType": "bug",
            "issueResolveState": "Closed",
            "issueReopenState": "Open",
            "issueSecurityId": "32168",
            "severityPriorityMappings": {
                "name": "major-major",
                "mappings": [
                    {"priority": "Minor"},
                    {"priority": "Major"},
                    {"priority": "Critical"},
                ],
            },
        },
    )
    jira_client = mocker.create_autospec(spec=JiraClient)
    jira_client.can_create_issues.side_effect = JIRAError(status_code=401)
    # no error for 401
    board_is_valid(
        jira=jira_client,
        board=board,
        default_issue_type="task",
        default_reopen_state="new",
        jira_server_priorities={"Minor": "1", "Major": "2", "Critical": "3"},
        public_projects=[],
    )
