from collections.abc import MutableMapping
from typing import Any

from pydantic import (
    BaseModel,
    ValidationError,
)


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
            else:
                if isinstance(field.type_, type) and issubclass(field.type_, str):
                    data[field.alias] = "I was too lazy to define a string here"
                elif isinstance(field.type_, type) and issubclass(field.type_, int):
                    data[field.alias] = 42
                elif isinstance(field.type_, type) and issubclass(field.type_, bool):
                    data[field.alias] = False
        else:
            if isinstance(field.type_, type) and issubclass(field.type_, BaseModel):
                if isinstance(data[field.alias], dict):
                    data[field.alias] = data_default_none(
                        field.type_, data[field.alias]
                    )
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
