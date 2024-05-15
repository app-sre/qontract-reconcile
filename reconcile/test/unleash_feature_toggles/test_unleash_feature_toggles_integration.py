from collections.abc import Callable
from unittest.mock import MagicMock, call

import pytest

from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    UnleashInstanceV1,
    UnleashProjectV1,
)
from reconcile.unleash_feature_toggles.integration import (
    UnleashFeatureToggleDeleteError,
    UnleashTogglesIntegration,
)
from reconcile.utils.unleash.server import Environment, Project


def test_unleash_feature_toggles_integration_early_exit(
    query_func: Callable, intg: UnleashTogglesIntegration
) -> None:
    early_exit_state = intg.get_early_exit_desired_state(query_func)
    assert "toggles" in early_exit_state


def test_unleash_feature_toggles_integration_get_unleash_instances(
    gql_class_factory: Callable, query_func: Callable, intg: UnleashTogglesIntegration
) -> None:
    assert intg.get_unleash_instances(query_func) == [
        gql_class_factory(
            UnleashInstanceV1,
            {
                "name": "unleash-instance",
                "adminToken": {
                    "path": "app-sre/creds/app-interface-stage-config",
                    "field": "INIT_ADMIN_API_TOKENS",
                },
                "allowUnmanagedFeatureToggles": True,
                "projects": [
                    {
                        "name": "default",
                        "feature_toggles": [
                            {
                                "name": "new-toggle",
                                "description": "description",
                                "provider": "unleash",
                                "unleash": {
                                    "type": "release",
                                    "impressionData": False,
                                },
                            },
                            {
                                "name": "needs-update",
                                "description": "I want a shiny new description",
                                "provider": "unleash",
                                "unleash": {
                                    "type": "release",
                                    "impressionData": False,
                                },
                            },
                            {
                                "name": "with-environments",
                                "description": "description",
                                "provider": "unleash",
                                "unleash": {
                                    "type": "release",
                                    "impressionData": False,
                                    "environments": '{"default": true, "development": true}',
                                },
                            },
                            {
                                "name": "delete-test",
                                "description": "description",
                                "delete": True,
                                "provider": "unleash",
                                "unleash": {
                                    "type": "release",
                                    "impressionData": False,
                                },
                            },
                            {
                                "name": "already-deleted",
                                "description": "description",
                                "delete": True,
                                "provider": "unleash",
                                "unleash": {
                                    "type": "release",
                                    "impressionData": False,
                                },
                            },
                        ],
                    }
                ],
            },
        )
    ]


def test_unleash_feature_toggles_integration_fetch_current_state(
    unleash_server_api: MagicMock,
    current_projects: list[Project],
    intg: UnleashTogglesIntegration,
) -> None:
    assert intg.fetch_current_state(unleash_server_api) == current_projects


def test_unleash_feature_toggles_integration_validate_unleash_projects(
    current_projects: list[Project],
    desired_projects: list[UnleashProjectV1],
    intg: UnleashTogglesIntegration,
) -> None:
    intg.validate_unleash_projects(
        current_projects=current_projects,
        desired_projects=desired_projects,
    )


def test_unleash_feature_toggles_integration_validate_unleash_projects_missing_project(
    current_projects: list[Project],
    desired_projects: list[UnleashProjectV1],
    intg: UnleashTogglesIntegration,
) -> None:
    desired_projects[0].name = "missing-project"
    with pytest.raises(ValueError):
        intg.validate_unleash_projects(
            current_projects=current_projects,
            desired_projects=desired_projects,
        )


@pytest.mark.parametrize("dry_run", [True, False])
def test_unleash_feature_toggles_integration_reconcile_feature_toggles(
    unleash_server_api: MagicMock,
    unleash_instances: list[UnleashInstanceV1],
    current_projects: list[Project],
    desired_projects: list[UnleashProjectV1],
    intg: UnleashTogglesIntegration,
    dry_run: bool,
) -> None:
    project_id = current_projects[0].name
    intg._reconcile_feature_toggles(
        client=unleash_server_api,
        instance=unleash_instances[0],
        project_id=project_id,
        dry_run=dry_run,
        current_state=current_projects[0].feature_toggles,
        desired_state=desired_projects[0].feature_toggles or [],
    )
    if not dry_run:
        unleash_server_api.create_feature_toggle.assert_called_with(
            project_id=project_id,
            name="new-toggle",
            description="description",
            type="release",
            impression_data=False,
        )
        unleash_server_api.update_feature_toggle.assert_called_with(
            project_id=project_id,
            name="needs-update",
            description="I want a shiny new description",
            type="release",
            impression_data=False,
        )
        unleash_server_api.delete_feature_toggle.assert_called_with(
            project_id=project_id, name="delete-test"
        )
    else:
        unleash_server_api.create_feature_toggle.assert_not_called()
        unleash_server_api.update_feature_toggle.assert_not_called()
        unleash_server_api.delete_feature_toggle.assert_not_called()


def test_unleash_feature_toggles_integration_reconcile_feature_toggles_unmanaged_toggles(
    unleash_server_api: MagicMock,
    unleash_instances: list[UnleashInstanceV1],
    current_projects: list[Project],
    desired_projects: list[UnleashProjectV1],
    intg: UnleashTogglesIntegration,
) -> None:
    instance = unleash_instances[0]
    instance.allow_unmanaged_feature_toggles = False
    with pytest.raises(UnleashFeatureToggleDeleteError):
        intg._reconcile_feature_toggles(
            client=unleash_server_api,
            instance=instance,
            project_id=current_projects[0].name,
            dry_run=True,
            current_state=current_projects[0].feature_toggles,
            desired_state=desired_projects[0].feature_toggles or [],
        )


@pytest.mark.parametrize("dry_run", [True, False])
def test_unleash_feature_toggles_integration_reconcile_states(
    unleash_server_api: MagicMock,
    unleash_instances: list[UnleashInstanceV1],
    current_projects: list[Project],
    desired_projects: list[UnleashProjectV1],
    intg: UnleashTogglesIntegration,
    dry_run: bool,
) -> None:
    project_id = current_projects[0].name
    intg._reconcile_states(
        client=unleash_server_api,
        instance=unleash_instances[0],
        project_id=project_id,
        dry_run=dry_run,
        current_state=current_projects[0].feature_toggles,
        desired_state=desired_projects[0].feature_toggles or [],
        available_environments=[
            Environment(name="default", enabled=True),
            Environment(name="development", enabled=True),
        ],
    )
    if not dry_run:
        assert unleash_server_api.set_feature_toggle_state.call_count == 2
        unleash_server_api.set_feature_toggle_state.assert_has_calls(
            [
                call(
                    project_id=project_id,
                    name="with-environments",
                    environment="default",
                    enabled=True,
                ),
                call(
                    project_id=project_id,
                    name="with-environments",
                    environment="development",
                    enabled=True,
                ),
            ],
            any_order=True,
        )
    else:
        unleash_server_api.set_feature_toggle_state.assert_not_called()


def test_unleash_feature_toggles_integration_reconcile_states_non_existing_env(
    unleash_server_api: MagicMock,
    unleash_instances: list[UnleashInstanceV1],
    current_projects: list[Project],
    desired_projects: list[UnleashProjectV1],
    intg: UnleashTogglesIntegration,
) -> None:
    with pytest.raises(ValueError):
        intg._reconcile_states(
            client=unleash_server_api,
            instance=unleash_instances[0],
            project_id=current_projects[0].name,
            dry_run=True,
            current_state=current_projects[0].feature_toggles,
            desired_state=desired_projects[0].feature_toggles or [],
            available_environments=[
                Environment(name="default", enabled=True),
            ],
        )
