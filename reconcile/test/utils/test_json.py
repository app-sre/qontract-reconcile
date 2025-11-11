import json
from typing import Any

from reconcile.utils.json import json_dumps


def test_basic_serialization() -> None:
    data = {"b": "value", "a": 42}
    result = json_dumps(data)
    assert json.loads(result) == data


def test_sort_keys_default() -> None:
    data = {"b": "value", "a": 42}
    result = json_dumps(data)
    assert result == '{"a": 42, "b": "value"}'


def test_compact_mode() -> None:
    data = {"b": "value", "a": 42}
    result = json_dumps(data, compact=True)
    assert result == '{"a":42,"b":"value"}'


def test_indented_pretty_print() -> None:
    data = {"b": {"key": "value"}, "a": 42}
    result = json_dumps(data, indent=2)
    expected = """{
  "a": 42,
  "b": {
    "key": "value"
  }
}"""
    assert result == expected


def test_cls() -> None:
    class CustomEncoder(json.JSONEncoder):
        def default(self, obj: Any) -> Any:
            if isinstance(obj, set):
                return list(obj)
            return super().default(obj)

    data = {"numbers": {1, 2, 3}}
    result = json_dumps(data, cls=CustomEncoder)
    assert json.loads(result) == {"numbers": [1, 2, 3]}
