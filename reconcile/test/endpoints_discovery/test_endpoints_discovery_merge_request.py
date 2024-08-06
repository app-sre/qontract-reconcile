from textwrap import dedent

import pytest

from reconcile.endpoints_discovery.merge_request import EPDInfo, Renderer, create_parser
from reconcile.utils.merge_request_manager.parser import Parser


def test_endpoints_discovery_merge_request_render_title() -> None:
    r = Renderer()
    assert (
        r.render_title() == "[auto] endpoints-discovery: update application endpoints"
    )


def test_endpoints_discovery_merge_request_render_description() -> None:
    r = Renderer()
    assert (
        r.render_description(hash="123456")
        == """
This MR is triggered by app-interface's [endpoints-discovery](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/endpoints_discovery).

Please **do not remove the `ENDPOINTS-DISCOVERY` label** from this MR!

Parts of this description are used to manage the MR.

**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**

* integration: endpoints-discovery
* endpoints-discover-version: 1.0.0
* hash: 123456
"""
    )


@pytest.mark.parametrize(
    (
        "current_content",
        "endpoints_to_add",
        "endpoints_to_change",
        "endpoints_to_delete",
        "expected_content",
    ),
    [
        # add a new endpoint - no existing endpoints
        (
            dedent("""
                ---
                name: test
            """),
            [{"name": "endpoint1", "data": "data1"}],
            {},
            [],
            dedent("""
                ---
                name: test
                endPoints:
                - name: endpoint1
                  data: data1
            """).lstrip(),
        ),
        # add a new endpoint - existing endpoints
        (
            dedent("""
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
            """),
            [{"name": "endpoint1", "data": "data1"}],
            {},
            [],
            dedent("""
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
                - name: endpoint1
                  data: data1
            """).lstrip(),
        ),
        # change an existing endpoint - with other endpoints
        (
            dedent("""
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
                - name: endpoint1
                  data: data1
            """),
            [],
            {"endpoint1": {"name": "changed-name", "data": "changed-data"}},
            [],
            dedent("""
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
                - name: changed-name
                  data: changed-data
            """).lstrip(),
        ),
        # change an existing endpoint - no other endpoints
        (
            dedent("""
                ---
                name: test
                endPoints:
                - name: endpoint1
                  data: data1
            """),
            [],
            {"endpoint1": {"name": "changed-name", "data": "changed-data"}},
            [],
            dedent("""
                ---
                name: test
                endPoints:
                - name: changed-name
                  data: changed-data
            """).lstrip(),
        ),
        # delete an existing endpoint - with other endpoints
        (
            dedent("""
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
                - name: endpoint1
                  data: data1
            """),
            [],
            {},
            ["endpoint1"],
            dedent("""
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
            """).lstrip(),
        ),
        # delete an existing endpoint - no other endpoints
        (
            dedent("""
                ---
                name: test
                endPoints:
                - name: endpoint1
                  data: data1
            """),
            [],
            {},
            ["endpoint1"],
            dedent("""
                ---
                name: test
                endPoints: []
            """).lstrip(),
        ),
        # delete two existing endpoints
        (
            dedent("""
                ---
                name: test
                endPoints:
                - name: endpoint1
                  data: data
                - name: endpoint2
                  data: data
                - name: endpoint3
                  data: data1
            """),
            [],
            {},
            ["endpoint1", "endpoint3"],
            dedent("""
                ---
                name: test
                endPoints:
                - name: endpoint2
                  data: data
            """).lstrip(),
        ),
        # add, change and delete existing endpoints
        (
            dedent("""
                ---
                name: test
                endPoints:
                - name: endpoint1
                  data: data1
                - name: endpoint2
                  data: data2
                - name: endpoint3
                  data: data3
            """),
            [{"name": "new-endpoint", "data": "new-data"}],
            {"endpoint2": {"name": "changed-name", "data": "changed-data"}},
            ["endpoint1"],
            dedent("""
                ---
                name: test
                endPoints:
                - name: changed-name
                  data: changed-data
                - name: endpoint3
                  data: data3
                - name: new-endpoint
                  data: new-data
            """).lstrip(),
        ),
    ],
)
def test_endpoints_discovery_merge_request_render_merge_request_content(
    current_content: str,
    endpoints_to_add: list[dict],
    endpoints_to_change: dict[str, dict],
    endpoints_to_delete: list[str],
    expected_content: str,
) -> None:
    r = Renderer()
    content = r.render_merge_request_content(
        current_content=current_content,
        endpoints_to_add=endpoints_to_add,
        endpoints_to_change=endpoints_to_change,
        endpoints_to_delete=endpoints_to_delete,
    )
    assert content == expected_content


def test_endpoints_discovery_merge_request_create_parser() -> None:
    parser = create_parser()
    assert isinstance(parser, Parser)


def test_endpoints_discovery_merge_request_edp_info() -> None:
    edp_info = EPDInfo(hash="123456")
    assert edp_info.integration
    assert edp_info.hash == "123456"
