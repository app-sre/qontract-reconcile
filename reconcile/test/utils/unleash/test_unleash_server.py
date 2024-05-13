import pytest

from reconcile.utils.unleash.server import (
    Environment,
    FeatureToggle,
    FeatureToggleType,
    Project,
    UnleashServer,
)


def test_unleash_server_projects(client: UnleashServer) -> None:
    assert client.projects() == [
        Project(pk="default", name="Default", feature_toggles=[])
    ]


def test_unleash_server_projects_with_toggles(client: UnleashServer) -> None:
    assert client.projects(include_feature_toggles=True) == [
        Project(
            pk="default",
            name="Default",
            feature_toggles=[
                FeatureToggle(
                    name="toggle-1",
                    type="release",
                    description="just a test toggle",
                    impression_data=False,
                    environments=[
                        Environment(name="default", enabled=True),
                        Environment(name="development", enabled=False),
                    ],
                ),
                FeatureToggle(
                    name="toggle-2",
                    type="release",
                    description="see above",
                    impression_data=False,
                    environments=[
                        Environment(name="default", enabled=False),
                        Environment(name="development", enabled=False),
                    ],
                ),
            ],
        )
    ]


def test_unleash_server_feature_toggles(client: UnleashServer) -> None:
    assert client.feature_toggles(project_id="default") == [
        FeatureToggle(
            name="toggle-1",
            type="release",
            description="just a test toggle",
            impression_data=False,
            environments=[
                Environment(name="default", enabled=True),
                Environment(name="development", enabled=False),
            ],
        ),
        FeatureToggle(
            name="toggle-2",
            type="release",
            description="see above",
            impression_data=False,
            environments=[
                Environment(name="default", enabled=False),
                Environment(name="development", enabled=False),
            ],
        ),
    ]


def test_unleash_server_environments(client: UnleashServer) -> None:
    assert client.environments(project_id="default") == [
        Environment(name="default", enabled=True),
        Environment(name="development", enabled=True),
        Environment(name="production", enabled=True),
    ]


def test_unleash_server_create_feature_toggle(client: UnleashServer) -> None:
    client.create_feature_toggle(
        project_id="default",
        name="toggle-3",
        description="test",
        type=FeatureToggleType["release"],
        impression_data=False,
    )


def test_unleash_server_update_feature_toggle(client: UnleashServer) -> None:
    client.update_feature_toggle(
        project_id="default",
        name="toggle-1",
        description="test",
        type=FeatureToggleType["release"],
        impression_data=False,
    )


def test_unleash_server_delete_feature_toggle(client: UnleashServer) -> None:
    client.delete_feature_toggle(project_id="default", name="toggle-1")


@pytest.mark.parametrize("enabled", [True, False])
def test_unleash_server_set_feature_toggle_state(
    client: UnleashServer, enabled: bool
) -> None:
    client.set_feature_toggle_state(
        project_id="default",
        name="toggle-1",
        environment="development",
        enabled=enabled,
    )
