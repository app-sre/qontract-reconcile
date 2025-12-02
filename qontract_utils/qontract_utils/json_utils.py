import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel
from pydantic.main import IncEx

JSON_COMPACT_SEPARATORS = (",", ":")


def pydantic_encoder(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump()

    if is_dataclass(obj):
        return asdict(obj)  # type: ignore[arg-type]

    if isinstance(obj, datetime | date):
        return obj.isoformat()

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, Decimal):
        return float(obj)

    raise TypeError(
        f"Object of type '{obj.__class__.__name__}' is not JSON serializable"
    )


def json_dumps(
    data: Any,
    *,
    compact: bool = False,
    indent: int | None = None,
    cls: type[json.JSONEncoder] | None = None,
    defaults: Callable[[Any], Any] | None = None,
    by_alias: bool = True,
    exclude_none: bool = False,
    exclude: IncEx | None = None,
    mode: Literal["json", "python"] = "json",
) -> str:
    """Serialize data to consistent JSON formatted string with sorted keys.

    Args:
        data: The data to serialize.
        compact: If True, use compact separators (no spaces).
        indent: If specified, pretty-print with this many spaces of indentation.
        cls: Custom JSONEncoder subclass for serialization.
        defaults: Default function for non-serializable objects.
        by_alias: Use field aliases for Pydantic models.
        exclude_none: Exclude None values for Pydantic models.
        exclude: Set of field names to exclude for Pydantic models.
        mode: Serialization mode for Pydantic models (json or python).

    Returns:
        JSON formatted string with sorted keys.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump(
            mode=mode, by_alias=by_alias, exclude_none=exclude_none, exclude=exclude
        )
        if mode == "python":
            defaults = pydantic_encoder
    separators = JSON_COMPACT_SEPARATORS if compact else None
    return json.dumps(
        data,
        indent=indent,
        separators=separators,
        sort_keys=True,
        cls=cls,
        default=defaults,
    )


def json_loads(data: str) -> Any:
    """Deserialize JSON string to Python object.

    Args:
        data: JSON formatted string to deserialize.

    Returns:
        Python object (dict, list, str, int, float, bool, or None).

    Raises:
        json.JSONDecodeError: If data is not valid JSON.
    """
    return json.loads(data)
