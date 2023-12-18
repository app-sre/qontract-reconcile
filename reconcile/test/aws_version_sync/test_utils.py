import json
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Any

import httpretty as httpretty_module
import pytest

from reconcile.aws_version_sync.utils import (
    get_values,
    override_values,
    prom_get,
    uniquify,
)


def test_prom_get(httpretty: httpretty_module) -> None:
    url = "http://prom.com"
    httpretty.register_uri(
        "GET",
        f"{url}/api/v1/query",
        status=200,
        body=json.dumps({
            "data": {
                "result": [
                    {"metric": "data1"},
                    {"metric": "data2"},
                ],
            }
        }),
        content_type="text/json",
    )

    assert prom_get(url, token="foobar", params={"query": "bar"}) == ["data1", "data2"]
    assert httpretty.last_request().headers.get("accept") == "application/json"
    assert httpretty.last_request().headers.get("authorization") == "Bearer foobar"
    assert httpretty.last_request().querystring == {"query": ["bar"]}


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
