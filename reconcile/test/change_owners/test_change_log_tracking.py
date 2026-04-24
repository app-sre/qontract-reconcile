from collections.abc import Callable
from typing import Any
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import (
    Project,
    ProjectCommit,
    ProjectCommitManager,
)
from pytest_mock import MockerFixture

from reconcile.change_owners.change_log_tracking import (
    ChangeLog,
    ChangeLogIntegration,
    ChangeLogIntegrationParams,
    ChangeLogItem,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypesQueryData,
)
from reconcile.gql_definitions.common.apps import AppV1
from reconcile.utils.gql import GqlApi

APP_PATH = "/services/a/app.yml"
MERGED_AT = "2024-01-01T00:00:00Z"
COMMIT_SHA = "commit_sha"


def setup_mocks(
    mocker: MockerFixture,
    gql_api_builder: Callable[..., GqlApi],
    gql_class_factory: Callable[..., ChangeTypesQueryData],
    apps: list[AppV1],
    datafiles: dict[str, Any],
    commit_message: str,
) -> dict[str, Any]:
    data = gql_class_factory(ChangeTypesQueryData, {})
    mocked_gql_api = gql_api_builder(data.model_dump(by_alias=True))
    mocker.patch(
        "reconcile.change_owners.change_log_tracking.gql"
    ).get_api.return_value = mocked_gql_api
    mocker.patch(
        "reconcile.change_owners.change_log_tracking.get_apps",
        return_value=apps,
    )
    mocker.patch(
        "reconcile.change_owners.change_log_tracking.get_namespaces",
        return_value=[],
    )
    mocker.patch(
        "reconcile.change_owners.change_log_tracking.get_jenkins_configs",
        return_value=[],
    )

    mocked_state = mocker.patch(
        "reconcile.change_owners.change_log_tracking.init_state",
        autospec=True,
    ).return_value
    mocked_state.ls.return_value = ["/commit_sha.json"]
    mocked_state.get.return_value = {
        "datafiles": datafiles,
        "resources": {},
    }

    mocked_gl = mocker.patch(
        "reconcile.change_owners.change_log_tracking.init_gitlab", autospec=True
    ).return_value
    project = create_autospec(Project)
    project.default_branch = "master"
    project.commits = create_autospec(ProjectCommitManager)
    commit = create_autospec(
        ProjectCommit,
        committed_date=MERGED_AT,
        message=commit_message,
    )
    project.commits.get.return_value = commit
    mocked_gl.project = project

    return {
        "state": mocked_state,
        "gl": mocked_gl,
    }


@pytest.mark.parametrize(
    ["commit_message", "expected_description"],
    [
        ("Merge branch 'dev' into 'master'\n\nmy title", "my title"),
        ("my title (!123)\n\nother messages", "my title (!123)"),
        ("my title", "my title"),
    ],
)
def test_change_log_tracking_with_deleted_app(
    mocker: MockerFixture,
    gql_api_builder: Callable[..., GqlApi],
    gql_class_factory: Callable[..., ChangeTypesQueryData],
    commit_message: str,
    expected_description: str,
) -> None:
    mocks = setup_mocks(
        mocker,
        gql_api_builder,
        gql_class_factory,
        apps=[],
        datafiles={
            "/services/a/namespaces/b.yml": {
                "datafilepath": "/services/a/namespaces/b.yml",
                "datafileschema": "/openshift/namespace-1.yml",
                "old": {
                    "$schema": "/openshift/namespace-1.yml",
                    "app": {
                        "$ref": APP_PATH,
                    },
                },
            }
        },
        commit_message=commit_message,
    )
    expected_change_log = ChangeLog(
        items=[
            ChangeLogItem(
                apps=[APP_PATH],
                change_types=[],
                commit=COMMIT_SHA,
                description=expected_description,
                error=False,
                merged_at=MERGED_AT,
            ),
        ]
    )
    integration = ChangeLogIntegration(
        ChangeLogIntegrationParams(
            gitlab_project_id="test",
            process_existing=True,
            commit=None,
        )
    )

    integration.run(dry_run=False)

    mocks["state"].add.assert_called_once_with(
        "bundle-diffs.json",
        expected_change_log.model_dump(),
        force=True,
    )
