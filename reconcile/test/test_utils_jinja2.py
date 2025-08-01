import tempfile

import pytest
from jsonpath_ng.exceptions import JsonPathParserError

from reconcile.utils.jinja2.filters import (
    extract_jsonpath,
    hash_list,
    json_pointers,
    matches_jsonpath,
    str_format,
)
from reconcile.utils.jinja2.utils import _process_sloth_output


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


def test_process_sloth_output_schema_compliance() -> None:
    """Test that _process_sloth_output removes non-schema-compliant elements."""
    mock_sloth_output = """---
        groups:
        - name: test-group
          rules:
          - record: test_metric
            expr: vector(1)
            labels:
              sloth_id: test-id
              sloth_service: test-service
              service: app-interface
          - alert: TestAlert
            expr: vector(1)
            labels:
              sloth_severity: critical
              service: app-interface
              severity: critical
            annotations:
              title: Test Alert Title
              summary: Test summary
    """

    with tempfile.NamedTemporaryFile(
        encoding="utf-8", mode="w", suffix=".yml", delete=False
    ) as f:
        f.write(mock_sloth_output)
        f.flush()
        result = _process_sloth_output(f.name)
        # Should remove document separator
        assert not result.startswith("---")
        # Should remove sloth_* labels
        assert "sloth_id:" not in result
        assert "sloth_service:" not in result
        assert "sloth_severity:" not in result
        # Should remove title annotations
        assert "title:" not in result
        # Should preserve schema-compliant elements
        assert "service: app-interface" in result
        assert "severity: critical" in result
        assert "summary: Test summary" in result
