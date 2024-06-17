from collections.abc import (
    Callable,
    MutableMapping,
    Sequence,
)
from typing import Any

import pytest

from reconcile.glitchtip_project_dsn.integration import (
    LABELS,
    fetch_current_state,
    fetch_desired_state,
    projects_query,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import GlitchtipProjectV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.glitchtip import GlitchtipClient
from reconcile.utils.oc_map import OCMap
from reconcile.utils.openshift_resource import ResourceInventory


@pytest.fixture
def projects(
    fx: Fixtures,
    data_factory: Callable[
        [type[GlitchtipProjectV1], MutableMapping[str, Any]], MutableMapping[str, Any]
    ],
) -> list[GlitchtipProjectV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        raw_data = fx.get_anymarkup("dsn_projects.yml")
        return {
            "glitchtip_projects": [
                data_factory(GlitchtipProjectV1, item)
                for item in raw_data["glitchtip_projects"]
            ]
        }

    return projects_query(q)


def test_project_query(projects: Sequence[GlitchtipProjectV1]) -> None:
    assert len(projects) == 2
    assert len(projects[0].namespaces) == 2
    assert projects[0].namespaces[0].name == "namespace-1"
    assert projects[0].namespaces[0].cluster.name == "cluster-1"
    assert projects[0].namespaces[1].name == "namespace-1"
    assert projects[0].namespaces[1].cluster.name == "cluster-2"
    assert projects[1].name == "project-does-not-exist-yet"
    assert len(projects[1].namespaces) == 1
    assert projects[1].namespaces[0].name == "namespace-1"


def test_fetch_current_state(
    oc_map: OCMap, projects: Sequence[GlitchtipProjectV1]
) -> None:
    ri = ResourceInventory()
    fetch_current_state(projects[0], oc_map, ri)
    # see oc_map fixture for the mocked data
    assert ri.get_current("cluster-1", "namespace-1", "Secret", "fake-secret")


def test_desire_state(
    glitchtip_client: GlitchtipClient,
    glitchtip_server_full_api_response: None,
    projects: Sequence[GlitchtipProjectV1],
) -> None:
    ri = ResourceInventory()
    fetch_desired_state(
        glitchtip_projects=projects, ri=ri, glitchtip_client=glitchtip_client
    )
    secret = ri.get_desired(
        "cluster-1", "namespace-1", "Secret", "apollo-11-flight-control-dsn"
    )
    assert secret.body == {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": "apollo-11-flight-control-dsn",
            "labels": LABELS,
        },
        "type": "Opaque",
        "stringData": {
            "dsn": "http://public_dsn",
            "security_endpoint": "http://security_endpoint",
        },
    }
