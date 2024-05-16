from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    UnleashInstanceV1,
    UnleashProjectV1,
)
from reconcile.test.fixtures import Fixtures
from reconcile.unleash_feature_toggles.integration import (
    UnleashTogglesIntegration,
    UnleashTogglesIntegrationParams,
)
from reconcile.utils.unleash.server import (
    Environment,
    FeatureToggle,
    Project,
    UnleashServer,
)


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("unleash")


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("instances.yml")


@pytest.fixture
def intg(mocker: MockerFixture) -> UnleashTogglesIntegration:
    integ = UnleashTogglesIntegration(UnleashTogglesIntegrationParams())
    integ._secret_reader = mocker.MagicMock()
    integ._secret_reader.read_all_secret.return_value = {  # type: ignore
        "aws_access_key_id": "access_key",
        "aws_secret_access_key": "secret_key",
    }
    return integ


@pytest.fixture
def query_func(
    data_factory: Callable[
        [type[UnleashInstanceV1], Mapping[str, Any]], Mapping[str, Any]
    ],
    raw_fixture_data: dict[str, Any],
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "instances": [
                data_factory(UnleashInstanceV1, item)
                for item in raw_fixture_data["instances"]
            ]
        }

    return q


@pytest.fixture
def unleash_instances(
    query_func: Callable, intg: UnleashTogglesIntegration
) -> list[UnleashInstanceV1]:
    return intg.get_unleash_instances(query_func)


@pytest.fixture
def current_projects() -> list[Project]:
    return [
        Project(
            pk="default",
            name="Default",
            feature_toggles=[
                FeatureToggle(
                    name="needs-update",
                    type="release",
                    description="no description yet",
                    impression_data=False,
                    environments=[],
                ),
                FeatureToggle(
                    name="with-environments",
                    type="release",
                    description="description",
                    impression_data=False,
                    environments=[
                        Environment(name="default", enabled=False),
                        Environment(name="development", enabled=False),
                    ],
                ),
                FeatureToggle(
                    name="delete-test",
                    type="release",
                    description="description",
                    impression_data=False,
                    environments=[],
                ),
                FeatureToggle(
                    name="unmanaged-toggle",
                    type="release",
                    description="description",
                    impression_data=False,
                    environments=[],
                ),
            ],
        )
    ]


@pytest.fixture
def desired_projects(
    unleash_instances: list[UnleashInstanceV1],
) -> list[UnleashProjectV1]:
    assert len(unleash_instances) == 1
    assert unleash_instances[0].projects
    return unleash_instances[0].projects


@pytest.fixture
def unleash_server_api(
    mocker: MockerFixture, current_projects: list[Project]
) -> MagicMock:
    mocker.patch("reconcile.unleash_feature_toggles.integration.UnleashServer")
    api = mocker.MagicMock(spec=UnleashServer)
    # keep in sync with instances.yml
    api.projects.return_value = current_projects
    return api
