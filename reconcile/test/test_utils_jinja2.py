import os
import tempfile
from unittest.mock import MagicMock

import pytest
import yaml
from jsonpath_ng.exceptions import JsonPathParserError
from pytest_mock import MockerFixture

from reconcile.utils.jinja2.filters import (
    extract_jsonpath,
    hash_list,
    json_pointers,
    matches_jsonpath,
    str_format,
)
from reconcile.utils.jinja2.utils import sloth_alerts
from reconcile.utils.sloth import process_sloth_output


def test_hash_list_empty() -> None:
    assert hash_list([])[:6] == "ca9781"


def test_hash_list_string() -> None:
    assert hash_list(["a", "b"])[:6] == "38760e"
    assert hash_list(["b", "a"])[:6] == "38760e"


def test_hash_list_int() -> None:
    assert hash_list([1, 2])[:6] == "f37508"
    assert hash_list([2, 1])[:6] == "f37508"


def test_hash_list_bool() -> None:
    assert hash_list([True, False])[:6] == "e0ca28"
    assert hash_list([False, True])[:6] == "e0ca28"


def test_hash_list_error() -> None:
    with pytest.raises(RuntimeError):
        hash_list([{}])

    with pytest.raises(RuntimeError):
        hash_list([[]])

    with pytest.raises(RuntimeError):
        hash_list(["a", {}])


def test_extract_jsonpath_dict_basic() -> None:
    input = {"a": "A", "b": {"b1": "B1", "b2": ["B", 2]}}
    assert extract_jsonpath(input, "a") == ["A"]
    assert extract_jsonpath(input, "b.b1") == ["B1"]
    assert extract_jsonpath(input, "b.b2") == [["B", 2]]
    assert extract_jsonpath(input, "b.b2[0]") == ["B"]
    assert extract_jsonpath(input, "c") == []


def test_extract_jsonpath_dict_multiple() -> None:
    input = {
        "items": [
            {"name": "a", "value": "A"},
            {"name": "b", "value": "B1"},
            {"name": "b", "value": "B2"},
        ]
    }
    assert extract_jsonpath(input, "items[0]") == [{"name": "a", "value": "A"}]
    assert extract_jsonpath(input, "items[?(@.name=='a')]") == [
        {"name": "a", "value": "A"}
    ]
    assert extract_jsonpath(input, "items[?(@.name=='a')].value") == ["A"]
    assert extract_jsonpath(input, "items[?(@.name=='b')]") == [
        {"name": "b", "value": "B1"},
        {"name": "b", "value": "B2"},
    ]
    assert extract_jsonpath(input, "items[?(@.name=='b')].value") == ["B1", "B2"]
    assert extract_jsonpath(input, "items[?(@.name=='c')].value") == []


def test_extract_jsonpath_list() -> None:
    input = ["a", "b"]
    assert extract_jsonpath(input, "[0]") == ["a"]


def test_extract_jsonpath_str() -> None:
    assert extract_jsonpath("a", "[0]") == ["a"]
    assert extract_jsonpath("a", "something") == []


def test_extract_jsonpath_none() -> None:
    assert extract_jsonpath(None, "a") == []


def test_extract_jsonpath_errors() -> None:
    input = {"a": "A", "b": "B"}
    with pytest.raises(JsonPathParserError):
        extract_jsonpath(input, "THIS IS AN INVALID JSONPATH]")
    with pytest.raises(AssertionError):
        extract_jsonpath("a", "")


def test_matches_jsonpath() -> None:
    input = {"a": "A", "b": "B"}
    assert matches_jsonpath(input, "a")
    assert not matches_jsonpath(input, "c")
    with pytest.raises(JsonPathParserError):
        matches_jsonpath(input, "THIS IS AN INVALID JSONPATH]")
    with pytest.raises(AssertionError):
        matches_jsonpath("a", "")
    with pytest.raises(AssertionError):
        matches_jsonpath("a", None)


def test_json_pointers() -> None:
    input = {
        "items": [
            {"name": "a", "value": "A"},
            {"name": "b", "value": "B1"},
            {"name": "b", "value": "B2"},
        ]
    }
    assert json_pointers(input, "items") == ["/items"]
    assert json_pointers(input, "items[*]") == ["/items/0", "/items/1", "/items/2"]
    assert json_pointers(input, "items[0]") == ["/items/0"]
    assert json_pointers(input, "items[0].name") == ["/items/0/name"]
    assert json_pointers(input, "items[4]") == []
    assert json_pointers(input, "items[4].name") == []

    assert json_pointers(input, "items[?@.name=='a']") == ["/items/0"]
    assert json_pointers(input, "items[?@.name=='b']") == ["/items/1", "/items/2"]
    assert json_pointers(input, "items[?@.name=='c']") == []


def test_str_format() -> None:
    value = "path/to/object"
    format = "s3://%s"
    assert str_format(value, format) == "s3://path/to/object"


def test_sloth_alerts(mocker: MockerFixture) -> None:
    """Test sloth_alerts function with SLO input processing"""
    # Sample SLO input data
    slos = [
        {
            "app_name": "test-app",
            "name": "Availability",
            "target": 95,
            "error_query": 'sum(rate(http_requests_total{status=~"5.."}[{{window}}]))',
            "total_query": "sum(rate(http_requests_total{}[{{window}}]))",
        },
        {
            "app_name": "test-app",
            "name": "Latency",
            "target": 99,
            "error_query": 'sum(rate(http_requests_latency_bucket{le="+Inf"}[{{window}}])) - sum(rate(http_requests_latency_bucket{le="1.0"}[{{window}}]))',
            "total_query": "sum(rate(http_requests_latency_bucket{}[{{window}}]))",
        },
    ]
    service = "test-app"

    fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures", "jinja2")
    expected_result_path = os.path.join(
        fixture_dir, "sloth_alerts_expected_result.yaml"
    )
    with open(expected_result_path, encoding="utf-8") as f:
        expected_result = f.read()
    result = sloth_alerts(slos, service)
    result_data = yaml.safe_load(result)
    expected_data = yaml.safe_load(expected_result)

    assert result_data == expected_data
