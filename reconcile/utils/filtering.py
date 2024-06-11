from typing import (
    TypeVar,
)

KeyType = TypeVar("KeyType")
ValueType = TypeVar("ValueType")


def remove_none_values_from_dict(
    a_dict: dict[KeyType, ValueType | None],
) -> dict[KeyType, ValueType]:
    """
    Creates a new dictionary based on the input dictionary but skips items
    with None values.
    """
    return {key: value for key, value in a_dict.items() if value is not None}
