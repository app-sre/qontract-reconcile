# ruff: noqa: FBT001

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, Field
from qontract_utils.json_utils import (
    JSON_COMPACT_SEPARATORS,
    json_dumps,
    json_loads,
    pydantic_encoder,
)


class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass
class Person:
    name: str
    age: int


class Address(BaseModel):
    street: str
    city: str
    zip_code: str = Field(alias="zipCode")


class User(BaseModel):
    username: str
    email: str | None = None
    status: Status = Status.ACTIVE


class SampleModel(BaseModel):
    a: int = Field(..., alias="alias")
    b: str
    c: datetime
    d: str | None = None
    e: Decimal


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
    assert JSON_COMPACT_SEPARATORS[0] in result
    assert " " not in result


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


@pytest.mark.parametrize(
    ("by_alias", "exclude_none", "expected"),
    [
        (
            False,
            False,
            '{"a":42,"b":"value","c":"1989-11-09T23:30:00+01:00","d":null,"e":"10.5"}',
        ),
        (
            False,
            True,
            '{"a":42,"b":"value","c":"1989-11-09T23:30:00+01:00","e":"10.5"}',
        ),
        (
            True,
            False,
            '{"alias":42,"b":"value","c":"1989-11-09T23:30:00+01:00","d":null,"e":"10.5"}',
        ),
        (
            True,
            True,
            '{"alias":42,"b":"value","c":"1989-11-09T23:30:00+01:00","e":"10.5"}',
        ),
    ],
)
def test_pydantic_model(by_alias: bool, exclude_none: bool, expected: str) -> None:
    data = SampleModel(
        alias=42,
        b="value",
        c=datetime(1989, 11, 9, 23, 30, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        d=None,
        e=Decimal("10.5"),
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


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (
            "json",
            '{"alias":42,"b":"value","c":"1989-11-09T23:30:00+01:00","d":null,"e":"10.5"}',
        ),
        (
            "python",
            '{"alias":42,"b":"value","c":"1989-11-09T23:30:00+01:00","d":null,"e":10.5}',
        ),
    ],
)
def test_pydantic_mode(mode: Literal["json", "python"], expected: str) -> None:
    data = SampleModel(
        alias=42,
        b="value",
        c=datetime(1989, 11, 9, 23, 30, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        d=None,
        e=Decimal("10.5"),
    )
    result = json_dumps(data, compact=True, mode=mode)
    assert result == expected


@pytest.mark.parametrize(
    ("exclude", "expected"),
    [
        (
            None,
            '{"alias":42,"b":"value","c":"1989-11-09T23:30:00+01:00","d":null,"e":"10.5"}',
        ),
        (
            {"b"},
            '{"alias":42,"c":"1989-11-09T23:30:00+01:00","d":null,"e":"10.5"}',
        ),
        (
            {"b", "d"},
            '{"alias":42,"c":"1989-11-09T23:30:00+01:00","e":"10.5"}',
        ),
        (
            {"a"},
            '{"b":"value","c":"1989-11-09T23:30:00+01:00","d":null,"e":"10.5"}',
        ),
    ],
)
def test_pydantic_exclude(exclude: set[str] | None, expected: str) -> None:
    data = SampleModel(
        alias=42,
        b="value",
        c=datetime(1989, 11, 9, 23, 30, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        d=None,
        e=Decimal("10.5"),
    )
    result = json_dumps(data, compact=True, exclude=exclude)
    assert result == expected


def test_json_dumps_dataclass() -> None:
    person = Person(name="Alice", age=30)
    result = json_dumps(person, defaults=pydantic_encoder)
    assert '"age": 30' in result
    assert '"name": "Alice"' in result


def test_json_dumps_datetime() -> None:
    dt = datetime(2025, 11, 17, 12, 30, 45, tzinfo=ZoneInfo("UTC"))
    data = {"timestamp": dt}
    result = json_dumps(data, defaults=pydantic_encoder)
    assert "2025-11-17T12:30:45+00:00" in result


def test_json_dumps_date() -> None:
    d = date(2025, 11, 17)
    data = {"date": d}
    result = json_dumps(data, defaults=pydantic_encoder)
    assert "2025-11-17" in result


def test_json_dumps_enum() -> None:
    data = {"status": Status.ACTIVE}
    result = json_dumps(data, defaults=pydantic_encoder)
    assert '"status": "active"' in result


def test_json_dumps_decimal() -> None:
    price = Decimal("19.99")
    data = {"price": price}
    result = json_dumps(data, defaults=pydantic_encoder)
    assert '"price": 19.99' in result


def test_json_loads_dict() -> None:
    json_str = '{"name": "test", "value": 42}'
    result = json_loads(json_str)
    assert result == {"name": "test", "value": 42}


def test_json_loads_list() -> None:
    json_str = '["item1", "item2", "item3"]'
    result = json_loads(json_str)
    assert result == ["item1", "item2", "item3"]


def test_json_loads_string() -> None:
    json_str = '"hello world"'
    result = json_loads(json_str)
    assert result == "hello world"


def test_json_loads_number() -> None:
    json_str = "42"
    result = json_loads(json_str)
    assert result == 42


def test_json_loads_boolean() -> None:
    json_str = "true"
    result = json_loads(json_str)
    assert result is True


def test_json_loads_null() -> None:
    json_str = "null"
    result = json_loads(json_str)
    assert result is None


def test_json_loads_nested_structure() -> None:
    json_str = '{"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}'
    result = json_loads(json_str)
    assert result == {
        "users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
    }


def test_json_loads_invalid_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        json_loads("{invalid json}")


def test_json_dumps_loads_roundtrip() -> None:
    original = {"name": "test", "values": [1, 2, 3], "nested": {"key": "value"}}
    serialized = json_dumps(original)
    deserialized = json_loads(serialized)
    assert deserialized == original


def test_pydantic_encoder_with_pydantic_model() -> None:
    user = User(username="testuser", email="test@example.com")
    result = pydantic_encoder(user)
    assert result == {
        "username": "testuser",
        "email": "test@example.com",
        "status": Status.ACTIVE,
    }


def test_pydantic_encoder_with_dataclass() -> None:
    person = Person(name="Alice", age=30)
    result = pydantic_encoder(person)
    assert result == {"name": "Alice", "age": 30}


def test_pydantic_encoder_with_datetime() -> None:
    dt = datetime(2025, 11, 17, 12, 30, 45, tzinfo=ZoneInfo("UTC"))
    result = pydantic_encoder(dt)
    assert result == "2025-11-17T12:30:45+00:00"


def test_pydantic_encoder_with_date() -> None:
    d = date(2025, 11, 17)
    result = pydantic_encoder(d)
    assert result == "2025-11-17"


def test_pydantic_encoder_with_enum() -> None:
    result = pydantic_encoder(Status.ACTIVE)
    assert result == "active"


def test_pydantic_encoder_with_decimal() -> None:
    price = Decimal("19.99")
    result = pydantic_encoder(price)
    assert result == 19.99


def test_pydantic_encoder_with_unsupported_type() -> None:
    with pytest.raises(TypeError, match="is not JSON serializable"):
        pydantic_encoder(object())
