import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, Field

from reconcile.utils.json import json_dumps, pydantic_encoder


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


class SampleModel(BaseModel):
    a: int = Field(..., alias="alias")
    b: str
    c: datetime
    d: str | None = None


@pytest.mark.parametrize(
    ("by_alias", "exclude_none", "expected"),
    [
        (False, False, '{"a":42,"b":"value","c":"1989-11-09T23:30:00+01:00","d":null}'),
        (False, True, '{"a":42,"b":"value","c":"1989-11-09T23:30:00+01:00"}'),
        (
            True,
            False,
            '{"alias":42,"b":"value","c":"1989-11-09T23:30:00+01:00","d":null}',
        ),
        (True, True, '{"alias":42,"b":"value","c":"1989-11-09T23:30:00+01:00"}'),
    ],
)
def test_pydantic_model(by_alias: bool, exclude_none: bool, expected: str) -> None:
    data = SampleModel(
        alias=42,
        b="value",
        c=datetime(1989, 11, 9, 23, 30, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        d=None,
    )
    result = json_dumps(
        data, compact=True, by_alias=by_alias, exclude_none=exclude_none
    )
    assert result == expected


def test_mixed_objects_with_pydantic_encoder() -> None:
    class NestedModel(BaseModel):
        x: int
        y: str

    class TestEnum(Enum):
        FOO = "bar"

    @dataclass
    class DataclassModel:
        path: str

    data = {
        "a": 42,
        "b": "value",
        "c": NestedModel(x=1, y="nested"),
        "d": datetime(1989, 11, 9, 23, 30, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        "e": TestEnum.FOO,
        "f": DataclassModel(path="/some/path"),
        "g": date(1989, 11, 9),
    }
    result = json_dumps(data, compact=True, defaults=pydantic_encoder)
    expected = '{"a":42,"b":"value","c":{"x":1,"y":"nested"},"d":"1989-11-09T23:30:00+01:00","e":"bar","f":{"path":"/some/path"},"g":"1989-11-09"}'
    assert result == expected
