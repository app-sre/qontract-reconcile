"""Tests for endpoints-discovery merge request rendering and hashing."""

import hashlib
import json
from textwrap import dedent

import jinja2
import pytest

from qontract_api.integrations.endpoints_discovery.domain import (
    AppEndpointPlan,
    DiscoveredRoute,
)
from qontract_api.integrations.endpoints_discovery.mr import (
    DATA_SEPARATOR,
    INTEGRATION,
    LABEL,
    VERSION,
    app_hash,
    compile_endpoint_name,
    endpoint_hash,
    endpoint_prefix,
    hash_apps,
    parse_endpoint_name,
    parse_merge_request_description,
    render_description,
    render_merge_request_content,
    render_template,
    render_title,
)

TEMPLATE = """\
name: {{ endpoint_name }}
url: {{ route.url }}
"""


def _endpoint(name: str, url: str | None = None) -> AppEndpointPlan:
    data = {"name": name} if url is None else {"name": name, "url": url}
    return AppEndpointPlan(name=name, data=data)


def _golden_app_plan() -> tuple[
    list[AppEndpointPlan], list[AppEndpointPlan], list[AppEndpointPlan]
]:
    adds = [
        _endpoint("endpoint-to-add-1", "https://fake-route.com:80"),
        _endpoint("endpoint-to-add-2", "https://fake-route.com:80"),
    ]
    changes = [
        _endpoint("endpoint-to-change-1", "https://fake-route.com:80"),
        _endpoint("endpoint-to-change-2", "https://fake-route.com:80"),
    ]
    # Deletes carry no rendered data, exactly like the legacy Endpoint model.
    deletes = [
        AppEndpointPlan(name="endpoint-to-delete-1"),
        AppEndpointPlan(name="endpoint-to-delete-2"),
    ]
    return adds, changes, deletes


# --- Naming ---


def test_endpoint_prefix() -> None:
    assert endpoint_prefix("cluster-1", "ns-1") == "endpoints-discovery/cluster-1/ns-1/"


def test_compile_endpoint_name() -> None:
    route = DiscoveredRoute(name="route-a", host="a.example.com", tls=True)
    assert (
        compile_endpoint_name("endpoints-discovery/cluster-1/ns-1/", route.name)
        == "endpoints-discovery/cluster-1/ns-1/route-a"
    )


def test_parse_endpoint_name() -> None:
    assert parse_endpoint_name(
        "endpoints-discovery/cluster-1/ns-1/route-a|route-b"
    ) == (
        "cluster-1",
        "ns-1",
        ["route-a", "route-b"],
    )


def test_parse_endpoint_name_rejects_manual_endpoint() -> None:
    with pytest.raises(ValueError, match="Invalid integration name"):
        parse_endpoint_name("manual-endpoint/cluster-1/ns-1/route-a")


def test_parse_endpoint_name_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="expected 4"):
        parse_endpoint_name("manual-endpoint")


# --- Template rendering ---


def test_render_template() -> None:
    route = DiscoveredRoute(name="route-a", host="a.example.com", tls=True)

    assert render_template(
        TEMPLATE, "endpoints-discovery/cluster-1/ns-1/route-a", route
    ) == {
        "name": "endpoints-discovery/cluster-1/ns-1/route-a",
        "url": "a.example.com:443",
    }


def test_render_template_sandboxes_dunder_access() -> None:
    """Underscore attributes must not be reachable from the template."""
    route = DiscoveredRoute(name="route-a", host="a.example.com", tls=True)

    with pytest.raises(jinja2.exceptions.SecurityError):
        render_template("value: {{ route.__class__ }}\n", "name", route)


def test_render_template_requires_defined_variables() -> None:
    route = DiscoveredRoute(name="route-a", host="a.example.com", tls=False)

    with pytest.raises(jinja2.exceptions.UndefinedError):
        render_template("value: {{ missing }}\n", "name", route)


# --- YAML merge ---


@pytest.mark.parametrize(
    ("current_content", "expected_content"),
    [
        (
            dedent("""\
                ---
                name: test
            """),
            dedent("""\
                ---
                name: test
                endPoints:
                - name: endpoint1
                  data: data1
            """),
        ),
        (
            dedent("""\
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
            """),
            dedent("""\
                ---
                name: test
                endPoints:
                - name: other-endpoint
                  data: data1
                - name: endpoint1
                  data: data1
            """),
        ),
    ],
)
def test_render_merge_request_content_add(
    current_content: str, expected_content: str
) -> None:
    result = render_merge_request_content(
        current_content=current_content,
        endpoints_to_add=[{"name": "endpoint1", "data": "data1"}],
        endpoints_to_change={},
        endpoints_to_delete=[],
    )

    assert result == expected_content


def test_render_merge_request_content_change_in_place() -> None:
    current = dedent("""\
        ---
        name: test
        endPoints:
        - name: other-endpoint
          data: data1
        - name: endpoint1
          data: data1
    """)

    result = render_merge_request_content(
        current_content=current,
        endpoints_to_add=[],
        endpoints_to_change={
            "endpoint1": {"name": "changed-name", "data": "changed-data"}
        },
        endpoints_to_delete=[],
    )

    assert result == dedent("""\
        ---
        name: test
        endPoints:
        - name: other-endpoint
          data: data1
        - name: changed-name
          data: changed-data
    """)


_EXISTING_ENDPOINT = dedent("""\
    ---
    name: test
    endPoints:
    - name: endpoint1
      data: data1
""")


def test_render_merge_request_content_add_skips_identical_existing() -> None:
    """An addition already present with the same content is not duplicated."""
    result = render_merge_request_content(
        current_content=_EXISTING_ENDPOINT,
        endpoints_to_add=[{"name": "endpoint1", "data": "data1"}],
        endpoints_to_change={},
        endpoints_to_delete=[],
    )

    assert result == _EXISTING_ENDPOINT


def test_render_merge_request_content_add_rejects_conflicting_existing() -> None:
    """An addition conflicting with existing content fails instead of duplicating."""
    with pytest.raises(ValueError, match="already exists with different content"):
        render_merge_request_content(
            current_content=_EXISTING_ENDPOINT,
            endpoints_to_add=[{"name": "endpoint1", "data": "other-data"}],
            endpoints_to_change={},
            endpoints_to_delete=[],
        )


def test_render_merge_request_content_delete_all() -> None:
    current = dedent("""\
        ---
        name: test
        endPoints:
        - name: endpoint1
          data: data1
    """)

    result = render_merge_request_content(
        current_content=current,
        endpoints_to_add=[],
        endpoints_to_change={},
        endpoints_to_delete=["endpoint1"],
    )

    assert result == dedent("""\
        ---
        name: test
        endPoints: []
    """)


# --- Hashing (golden values ported from the legacy suite) ---


def test_endpoint_hash_uses_legacy_json_encoding() -> None:
    """The endpoint hash must use sorted-key JSON with default separators.

    The legacy implementation hashed `json_dumps(Endpoint.model_dump())`, which
    serializes `{"name": ..., "data": ...}` with sorted keys. Any change here
    invalidates every open merge request.
    """
    expected = hashlib.sha256(
        json.dumps(
            {"data": {"name": "x", "url": "u"}, "name": "x"},
            sort_keys=True,
        ).encode()
    ).hexdigest()

    assert endpoint_hash("x", {"name": "x", "url": "u"}) == expected


def test_app_hash_matches_legacy_golden() -> None:
    """App hashes stay identical to the legacy integration's hashes.

    If this value changes, every open MR created by the legacy integration is
    classified as outdated and closed on the first run of the new integration.
    """
    adds, changes, deletes = _golden_app_plan()

    assert (
        app_hash("/path/app-1.yml", adds, changes, deletes)
        == "8b09ab363499304987686af3bbed5157ecb9fea164e334969e6ef85494f88f0e"
    )


def test_app_hash_is_order_independent() -> None:
    adds, changes, deletes = _golden_app_plan()

    assert app_hash("/path/app-1.yml", adds, changes, deletes) == app_hash(
        "/path/app-1.yml", list(reversed(adds)), changes, deletes
    )


def test_hash_apps_matches_legacy_golden() -> None:
    """Aggregate hash stays identical to the legacy integration's hash."""
    apps = [
        (name, app_hash(f"/path/{name}.yml", [], [], []))
        for name in ("app-1", "app-2", "app-3")
    ]

    assert (
        hash_apps(apps)
        == "289bc5c0644b5d297bd9546f778736fd25165177795dc5fdbe5421d6430b660d"
    )


def test_hash_apps_is_order_independent() -> None:
    apps = [(name, app_hash(f"/path/{name}.yml", [], [], [])) for name in ("b", "a")]

    assert hash_apps(apps) == hash_apps(list(reversed(apps)))


# --- MR text ---


def test_render_title() -> None:
    assert render_title() == "[auto] endpoints-discovery: update application endpoints"


def test_render_description_matches_legacy_text() -> None:
    """The description is parsed by the manager, so its text must not drift."""
    assert (
        render_description(plan_hash="123456")
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


def test_constants_match_legacy() -> None:
    assert INTEGRATION == "endpoints-discovery"
    assert VERSION == "1.0.0"
    assert LABEL == "ENDPOINTS-DISCOVERY"
    assert DATA_SEPARATOR == "**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"


def test_parse_merge_request_description_round_trip() -> None:
    metadata = parse_merge_request_description(render_description(plan_hash="abcdef"))

    assert metadata is not None
    assert metadata.integration == INTEGRATION
    assert metadata.version == VERSION
    assert metadata.hash == "abcdef"


def test_parse_merge_request_description_rejects_missing_separator() -> None:
    assert parse_merge_request_description("no machine readable data here") is None


def test_parse_merge_request_description_rejects_missing_fields() -> None:
    description = (
        "intro\n" + DATA_SEPARATOR + "\n\n* integration: endpoints-discovery\n"
    )

    assert parse_merge_request_description(description) is None
