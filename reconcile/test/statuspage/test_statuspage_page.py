from reconcile.gql_definitions.statuspage.statuspages import StatusPageV1
from reconcile.statuspage.page import build_status_page


def test_build_status_page_from_desired_state(
    status_page_v1: StatusPageV1,
):
    """
    Test the transformation from the GQL desired state into a
    StatusPage object
    """
    page = build_status_page(status_page_v1)
    assert page.name == "page"
    assert len(page.components) == 2
    assert {c.group_name for c in page.components if c.group_name} == {"group-1"}
    assert {c.name for c in page.components} == {"ai-component-1", "ai-component-2"}
