from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Any

import pytest
from pytest_httpserver import HTTPServer

from reconcile.aws_version_sync.utils import (
    get_values,
    override_values,
    prom_get,
    uniquify,
)


def test_prom_get(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/api/v1/query").respond_with_json({
        "data": {
            "result": [
                {"metric": "data1"},
                {"metric": "data2"},
            ],
        }
    })

    assert prom_get(
        httpserver.url_for(""), token="foobar", params={"query": "bar"}
    ) == ["data1", "data2"]
    req, _ = httpserver.log[0]
    assert req.headers.get("accept") == "application/json"
    assert req.headers.get("authorization") == "Bearer foobar"
    assert req.args["query"] == "bar"


@pytest.mark.parametrize(
    "items, expected",
    [
        (
            [],
            [],
        ),
        (
            [1, 2, 3],
            [1, 2, 3],
        ),
        (
            [1, 1, 2, 2, 3, 3],
            [1, 2, 3],
        ),
        (
            [1, 2, 3, 1, 2, 3],
            [1, 2, 3],
        ),
        (
            [1, 2, 3, 1, 2, 3, 1, 2, 3],
            [1, 2, 3],
        ),
        (
            [1, 2, 3, 1, 2, 3, 1, 2, 3, 4],
            [1, 2, 3, 4],
        ),
        (
            [1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 5],
            [1, 2, 3, 4, 5],
        ),
        (
            [1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 5, 6],
            [1, 2, 3, 4, 5, 6],
        ),
        (
            [1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 5, 6, 1],
            [1, 2, 3, 4, 5, 6],
        ),
        (
            [1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 5, 6, 1, 2],
            [1, 2, 3, 4, 5, 6],
        ),
    ],
)
def test_uniquify(items: Iterable[Any], expected: Iterable[Any]) -> None:
    assert uniquify(lambda x: x, items) == expected


def test_get_values() -> None:
    def _gql_get_resource_func(path: str) -> dict[str, Any]:
        assert path == "foo"
        return {
            "content": """
$schema: /aws/rds-defaults-1.yml
engine: postgres
name: postgres
username: postgres
engine_version: '13.5'
"""
        }

    assert get_values(_gql_get_resource_func, "foo") == {
        "engine": "postgres",
        "name": "postgres",
        "username": "postgres",
        "engine_version": "13.5",
    }


@pytest.mark.parametrize(
    "values, overrides, expected",
    [
        (
            {"engine_version": "13.5"},
            {},
            {"engine_version": "13.5"},
        ),
        (
            {"engine_version": "13.5"},
            {"engine_version": "13.6"},
            {"engine_version": "13.6"},
        ),
        (
            {"engine_version": "13.5"},
            {"apply_foobar": "true"},
            {"engine_version": "13.5", "apply_foobar": "true"},
        ),
        (
            {"engine_version": "13.5"},
            {"engine_version": "13.6", "apply_foobar": "true"},
            {"engine_version": "13.6", "apply_foobar": "true"},
        ),
    ],
)
def test_override_values(
    values: Mapping, overrides: Mapping, expected: Mapping
) -> None:
    assert override_values(values, overrides) == expected
