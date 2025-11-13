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
DEFAULT_JSON_STR = "{}"
DEFAULT_JSON: dict = {}

DataType = MutableMapping[str, Any] | str | int | bool | list | None


def _process_field_with_alias(
    field_info: dict[str, Any],
    data: DataType,
    alias: str | None,
    use_defaults: bool,
    definitions: list[dict[str, Any]] | None,
) -> DataType:
    """Process a field by recursively calling data_default_none and handling alias.

    This helper function encapsulates the common pattern used by 'default',
    'nullable', and 'model' field types where we need to:
    1. Recursively process the field's schema
    2. Handle data extraction via alias if data is a dict
    3. Update the data dict with the processed value if alias exists

    Args:
        field_info: Schema information for the field to process
        data: Input data (can be dict, primitive, list, or None)
        alias: Field alias for dict key access, or None for unnamed fields
        use_defaults: Whether to use default values for missing required fields
        definitions: Schema definitions for definition-ref fields

    Returns:
        Processed data value, or updated data dict if alias was provided
    """
    # Recursively process the field's schema
    value = data_default_none(
        field_info["schema"],
        data.get(alias) if isinstance(data, MutableMapping) and alias else data,
        use_defaults=use_defaults,
        definitions=definitions,
    )

    # For unnamed fields (in recursive calls), return value directly
    if not alias:
        return value

    # For named fields, update the data dict
    if not isinstance(data, MutableMapping):
        raise TypeError(
            f"Expected MutableMapping for field '{alias}', got {type(data).__name__}"
        )
    data[alias] = value
    return data


def data_default_none(
    klass: type[BaseModel] | dict,
    data: DataType,
    use_defaults: bool = True,
    definitions: list[dict[str, Any]] | None = None,
) -> DataType:
    """Set default values for required fields in Pydantic model data.

    This function recursively processes Pydantic model schemas and fills in
    missing fields with appropriate default values based on their type. It's
    primarily used to handle GraphQL query results where fields may be missing.

    Args:
        klass: Pydantic BaseModel class or schema dict to process
        data: Input data to fill with defaults (can be dict, primitive, list, or None)
        use_defaults: If True, use type-based defaults for missing required fields.
                     If False, raise ValueError for missing required fields.
        definitions: Schema definitions for definition-ref fields (e.g., VaultSecret).
                    Automatically extracted from models with "definitions" schema type.

    Returns:
        Data with defaults filled in. Return type matches input data structure.

    Field handling behavior:
        - Optional fields (T | None): Default to None if missing
        - Required primitives: Use DEFAULT_STRING, DEFAULT_INT, or DEFAULT_BOOL
        - Fields with explicit defaults: Use the provided default value
        - Lists: Default to empty list [] if missing, recursively process items
        - Nested models: Recursively process with data_default_none
        - Union types: Try each variant until one validates ("first match wins")

    Example:
        >>> class User(BaseModel):
        ...     name: str
        ...     age: int | None
        >>> data_default_none(User, {})
        {'name': 'I was too lazy to define a string here', 'age': None}
    """
    # =========================================================================
    # Extract schema from BaseModel class or use provided schema dict
    # =========================================================================
    if isinstance(klass, dict):
        # Recursive calls pass schema dict directly
        schema = klass
    else:
        # Extract schema from Pydantic BaseModel class
        match klass.__pydantic_core_schema__["type"]:
            case "definitions":
                # Models using definition-ref (e.g., VaultSecret fragments)
                schema = klass.__pydantic_core_schema__["schema"]["schema"]
                definitions = klass.__pydantic_core_schema__["definitions"]
            case _:
                # Standard models
                schema = klass.__pydantic_core_schema__["schema"]

    # =========================================================================
    # Get fields to process - either model fields or single schema
    # =========================================================================
    if schema["type"] == "model-fields":
        # Multiple fields in a model
        fields = schema["fields"].items()
    else:
        # Single field schema (used in recursive calls for field processing)
        fields = [(None, schema)]

    # =========================================================================
    # Process each field according to its schema type
    # =========================================================================
    for name, field_info in fields:
        # Use alias if defined (e.g., "serverUrl" instead of "server_url")
        alias = field_info.get("validation_alias", name)

        match field_info["type"]:
            # =================================================================
            # PRIMITIVE TYPES: str, int, bool
            # =================================================================
            case "str" | "int" | "bool" | "json":
                # If data is provided, return it as-is (don't override user data)
                if data is not None:
                    return data

                # If no defaults allowed, raise error for missing required field
                if not use_defaults:
                    raise ValueError(f"Field {alias or ''} is required but not set.")

                # Return type-specific default value
                match field_info["type"]:
                    case "str":
                        return DEFAULT_STRING
                    case "int":
                        return DEFAULT_INT
                    case "bool":
                        return DEFAULT_BOOL
                    case "json":
                        return DEFAULT_JSON_STR

            # =================================================================
            # FIELDS WITH EXPLICIT DEFAULT VALUES
            # =================================================================
            case "default":
                # If no data provided, use the field's default value
                if data is None:
                    return field_info["default"]

                # Data exists - recursively process it in case it's a complex type
                return _process_field_with_alias(
                    field_info, data, alias, use_defaults, definitions
                )

            # =================================================================
            # NULLABLE/OPTIONAL FIELDS: T | None
            # =================================================================
            case "nullable":
                # If no data provided, optional fields default to None
                if data is None:
                    return None

                # Data exists - recursively process the non-None value
                return _process_field_with_alias(
                    field_info, data, alias, use_defaults, definitions
                )

            # =================================================================
            # MODEL FIELDS: Nested Pydantic models within parent model
            # =================================================================
            case "model-field":
                # Ensure data is a dict (create empty dict if needed)
                # This allows processing models even when parent data is missing
                if not isinstance(data, MutableMapping):
                    data = {}

                # Recursively process the nested model
                data[alias] = data_default_none(
                    field_info["schema"],
                    data.get(alias),
                    use_defaults=use_defaults,
                    definitions=definitions,
                )

            # =================================================================
            # STANDALONE MODELS: BaseModel used as field type
            # =================================================================
            case "model":
                # Recursively process nested BaseModel
                return _process_field_with_alias(
                    field_info, data, alias, use_defaults, definitions
                )

            # =================================================================
            # DEFINITION REFERENCES: e.g., VaultSecret fragments
            # =================================================================
            case "definition-ref":
                # Definition-ref fields require a MutableMapping data structure
                assert isinstance(data, MutableMapping)

                # Definitions are required for resolving references
                if not definitions:
                    raise RuntimeError(
                        "definitions parameter is required for definition-ref fields"
                    )

                # Find the referenced schema definition by ref ID
                ref_schema = next(
                    definition
                    for definition in definitions
                    if definition["ref"] == field_info["schema_ref"]
                )

                # Recursively process using the referenced schema
                value = data_default_none(
                    ref_schema["schema"],
                    data.get(alias) if alias else data,
                    use_defaults=use_defaults,
                    definitions=definitions,
                )

                # For unnamed fields, return value directly
                if not alias:
                    return value

                data[alias] = value

            # =================================================================
            # UNION TYPES: T1 | T2 | ...
            # =================================================================
            case "union":
                # Strategy: Try each union variant until one validates successfully
                # This is a "first match wins" approach
                for sub_field in field_info["choices"]:
                    try:
                        # Try to process data with this union variant
                        # use_defaults=False ensures we only match existing data
                        sub_data = data_default_none(
                            sub_field,
                            # don't alter data structure here
                            dict(data) if isinstance(data, MutableMapping) else data,
                            use_defaults=use_defaults,
                            definitions=definitions,
                        )

                        # Validate the result matches the expected type
                        match sub_field["type"]:
                            case "str":
                                if not isinstance(sub_data, str):
                                    raise ValueError()
                            case "int":
                                if not isinstance(sub_data, int):
                                    raise ValueError()
                            case "bool":
                                if not isinstance(sub_data, bool):
                                    raise ValueError()
                            case "model":
                                if not isinstance(sub_data, dict):
                                    raise ValueError()
                                # Validate the dict can be instantiated as the model
                                sub_field["cls"].model_validate(sub_data)
                                if isinstance(data, MutableMapping):
                                    data.update(sub_data)

                        # If we get here, this union variant matched successfully
                        return data
                    except (ValidationError, ValueError):
                        # This variant didn't match, try the next one
                        continue

            # =================================================================
            # LIST TYPES: list[T]
            # =================================================================
            case "list":
                # If data is not a list, default to empty list
                if not isinstance(data, list):
                    return []

                # Recursively process each list item
                return [
                    data_default_none(
                        field_info["items_schema"],
                        item.get(alias)
                        if isinstance(item, MutableMapping) and alias
                        else item,
                        use_defaults=use_defaults,
                        definitions=definitions,
                    )
                    for item in data
                ]

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
