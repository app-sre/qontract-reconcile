from collections import UserList
from collections.abc import (
    MutableMapping,
)
from typing import Any

from croniter import croniter
from pydantic import (
    BaseModel,
    GetCoreSchemaHandler,
    ValidationError,
)
from pydantic_core import core_schema

DEFAULT_STRING = "I was too lazy to define a string here"
DEFAULT_INT = 42
DEFAULT_BOOL = False


def data_default_none(
    klass: type[BaseModel] | dict,
    data: MutableMapping[str, Any],
    use_defaults: bool = True,
    definitions: list[dict[str, Any]] | None = None,
) -> MutableMapping[str, Any]:
    """Set default values for required fields.

    If the field is:
    * optional - set to None
    * required and use_defaults is True - set to a default value depending on the type
    """
    if isinstance(klass, dict):
        # Handle the case where klass is already a schema dict
        schema = klass
    else:
        match klass.__pydantic_core_schema__["type"]:
            case "definitions":
                schema = klass.__pydantic_core_schema__["schema"]["schema"]
                definitions = klass.__pydantic_core_schema__["definitions"]
            case _:
                schema = klass.__pydantic_core_schema__["schema"]

    for name, field_info in schema["fields"].items():
        alias = field_info.get("validation_alias", name)
        if alias not in data:
            # Set defaults
            match field_info["schema"]["type"]:
                case "nullable":
                    data[alias] = None
                case "str":
                    if not use_defaults:
                        raise ValueError(f"Field {alias} is required but not set.")
                    data[alias] = DEFAULT_STRING
                case "int":
                    if not use_defaults:
                        raise ValueError(f"Field {alias} is required but not set.")
                    data[alias] = DEFAULT_INT
                case "bool":
                    if not use_defaults:
                        raise ValueError(f"Field {alias} is required but not set.")
                    data[alias] = DEFAULT_BOOL
        else:
            # Recursively set defaults for nested models
            match field_info["schema"]["type"]:
                case "model":
                    # Nested BaseModel
                    data[alias] = data_default_none(
                        field_info["schema"]["schema"],
                        data[alias],
                        definitions=definitions,
                    )
                case "definition-ref":
                    # Nested BaseModel via definition-ref. E.g. our VaultSecret fragment
                    if not definitions:
                        raise RuntimeError(
                            "definitions parameter is required for definition-ref fields"
                        )
                    ref_schema = next(
                        definition
                        for definition in definitions
                        if definition["ref"] == field_info["schema"]["schema_ref"]
                    )
                    data[alias] = data_default_none(
                        ref_schema["schema"],
                        data[alias],
                        definitions=definitions,
                    )
                case "union":
                    # Union field - only handle BaseModel members
                    for sub_field in field_info["schema"]["choices"]:
                        if isinstance(data[alias], dict):
                            try:
                                d = dict(data[alias])
                                d.update(
                                    data_default_none(
                                        sub_field["schema"], d, definitions=definitions
                                    )
                                )
                                # Lets confirm we found a matching union class
                                sub_field["cls"](**d)
                                data[alias] = d
                                break
                            except ValidationError:
                                continue
                case "list":
                    match field_info["schema"]["items_schema"]["type"]:
                        case "model":
                            # list[BaseModel]
                            data[alias] = [
                                data_default_none(
                                    field_info["schema"]["items_schema"]["schema"],
                                    item,
                                    definitions=definitions,
                                )
                                for item in data[alias]
                            ]
                        case "union":
                            # list[Union[...]]
                            for sub_data in data[alias]:
                                for sub_field in field_info["schema"]["items_schema"][
                                    "choices"
                                ]:
                                    if isinstance(sub_data, dict):
                                        try:
                                            d = dict(sub_data)
                                            d.update(
                                                data_default_none(
                                                    sub_field["schema"],
                                                    d,
                                                    definitions=definitions,
                                                )
                                            )
                                            # Lets confirm we found a matching union class
                                            sub_field["cls"](**d)
                                            sub_data.update(d)
                                            break
                                        except ValidationError:
                                            continue

    return data


class CSV(UserList[str]):
    """
    A pydantic custom type that converts a CSV into a list of strings. It
    also supports basic validation of length constraints.
    """

    @classmethod
    def __get_pydantic_core_schema__(  # noqa: PLW3201
        cls, source: type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.with_info_before_validator_function(
            cls._validate, core_schema.list_schema()
        )

    @classmethod
    def _validate(cls, __input_value: str, _: Any) -> list[str]:
        return [] if not __input_value else __input_value.split(",")


def cron_validator(value: str) -> str:
    """
    A pydantic validator for a cron expression.
    """
    try:
        croniter(value)
        return value
    except ValueError as e:
        raise ValueError(f"Invalid cron expression: {e}") from None
