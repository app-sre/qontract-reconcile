from collections.abc import (
    Callable,
    Generator,
    MutableMapping,
)
from typing import Any

from croniter import croniter
from pydantic import (
    BaseModel,
    ValidationError,
)
from pydantic import errors as pydantic_errors
from pydantic.fields import ModelField

DEFAULT_STRING = "I was too lazy to define a string here"
DEFAULT_INT = 42


def data_default_none(
    klass: type[BaseModel], data: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Set default values to None for required but optional fields."""
    for field in klass.__fields__.values():
        if not field.required:
            continue

        if field.alias not in data:
            # Settings defaults
            if field.allow_none:
                data[field.alias] = None
            elif isinstance(field.type_, type) and issubclass(field.type_, str):
                data[field.alias] = DEFAULT_STRING
            elif isinstance(field.type_, type) and issubclass(field.type_, bool):
                data[field.alias] = False
            elif isinstance(field.type_, type) and issubclass(field.type_, int):
                data[field.alias] = DEFAULT_INT
        elif isinstance(field.type_, type) and issubclass(field.type_, BaseModel):
            if isinstance(data[field.alias], dict):
                data[field.alias] = data_default_none(field.type_, data[field.alias])
            if isinstance(data[field.alias], list):
                data[field.alias] = [
                    data_default_none(field.type_, item)
                    for item in data[field.alias]
                    if isinstance(item, dict)
                ]
        elif field.sub_fields:
            if all(
                isinstance(sub_field.type_, type)
                and issubclass(sub_field.type_, BaseModel)
                for sub_field in field.sub_fields
            ):
                # Union[ClassA, ClassB] field
                for sub_field in field.sub_fields:
                    if isinstance(data[field.alias], dict):
                        try:
                            d = dict(data[field.alias])
                            d.update(data_default_none(sub_field.type_, d))
                            # Lets confirm we found a matching union class
                            sub_field.type_(**d)
                            data[field.alias] = d
                            break
                        except ValidationError:
                            continue
            elif isinstance(data[field.alias], list) and len(field.sub_fields) == 1:
                # list[Union[ClassA, ClassB]] field
                for sub_data in data[field.alias]:
                    for sub_field in field.sub_fields[0].sub_fields or []:
                        try:
                            d = dict(sub_data)
                            d.update(data_default_none(sub_field.type_, d))
                            # Lets confirm we found a matching union class
                            sub_field.type_(**d)
                            sub_data.update(d)
                            break
                        except ValidationError:
                            continue

    return data


class CSV(list[str]):
    """
    A pydantic custom type that converts a CSV into a list of strings. It
    also supports basic validation of length constraints.
    """

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # noqa: PLW3201
        yield cls.validate
        yield cls.length_validator

    @classmethod
    def validate(cls, value: str) -> list[str]:
        if not value:
            items = []
        else:
            items = value.split(",")
        return items

    @classmethod
    def length_validator(
        cls, v: "list[str]", values: dict, field: ModelField
    ) -> "list[str]":
        min_items = field.field_info.extra.get("csv_min_items")
        max_items = field.field_info.extra.get("csv_max_items")

        v_len = len(v)
        if min_items is not None and v_len < min_items:
            raise pydantic_errors.ListMinLengthError(limit_value=min_items)
        if max_items is not None and v_len > max_items:
            raise pydantic_errors.ListMaxLengthError(limit_value=max_items)
        return v


def cron_validator(value: str) -> str:
    """
    A pydantic validator for a cron expression.
    """
    try:
        croniter(value)
        return value
    except ValueError as e:
        raise ValueError(f"Invalid cron expression: {e}")
