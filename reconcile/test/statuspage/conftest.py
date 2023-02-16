import pytest

from reconcile.gql_definitions.statuspage.statuspages import StatusPageV1
from reconcile.statuspage.atlassian import AtlassianStatusPageProvider
from reconcile.test.fixtures import Fixtures
from reconcile.test.statuspage.fixtures import (
    construct_atlassian_page,
    construct_status_page_v1,
    describe_atlassian_component,
    describe_component_v1,
)


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("statuspage")


@pytest.fixture
def atlassian_page() -> AtlassianStatusPageProvider:
    return construct_atlassian_page(
        page_name="page",
        component_repr=[
            describe_atlassian_component(
                "id-1", "component-1", "group-1", "operational", "ai-component-1"
            ),
            describe_atlassian_component(
                "id-2", "component-2", None, "under_maintenance", "ai-component-2"
            ),
            describe_atlassian_component("id-3", "component-3", None, "degraded", None),
        ],
        groups=["group-1"],
    )


@pytest.fixture
def status_page_v1() -> StatusPageV1:
    return construct_status_page_v1(
        name="page",
        provider="atlassian",
        component_repr=[
            describe_component_v1(
                "ai-component-1", "component-1", "group-1", "operational"
            ),
            describe_component_v1("ai-component-2", "component-2", None, "operational"),
        ],
    )
