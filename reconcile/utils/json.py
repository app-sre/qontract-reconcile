import json
from typing import Any

from pydantic import BaseModel

JSON_COMPACT_SEPARATORS = (",", ":")


def json_dumps(
    data: Any,
    *,
    compact: bool = False,
    indent: int | None = None,
    cls: type[json.JSONEncoder] | None = None,
    # BaseModel dump parameters
    by_alias: bool = True,
    exclude_none: bool = False,
) -> str:
    """
    Serialize `data` to a consistent JSON formatted `str` with dict keys sorted.

    Args:
        data: The data to serialize.
        compact: If True, use compact separators (no spaces after commas or colons).
        indent: If specified, pretty-print the JSON with this many spaces of indentation.
        cls: A custom JSONEncoder subclass to use for serialization.
    Returns:
        A JSON formatted string.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump(
            mode="json", by_alias=by_alias, exclude_none=exclude_none
        )
    separators = JSON_COMPACT_SEPARATORS if compact else None
    return json.dumps(
        data,
        indent=indent,
        separators=separators,
        sort_keys=True,
        cls=cls,
    )
