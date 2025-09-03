import json
from typing import Any

JSON_COMPACT_SEPARATORS = (",", ":")


def json_dumps(
    data: Any,
    *,
    compact: bool = False,
    indent: int | None = None,
    cls: type[json.JSONEncoder] | None = None,
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
    separators = JSON_COMPACT_SEPARATORS if compact else None
    return json.dumps(
        data,
        indent=indent,
        separators=separators,
        sort_keys=True,
        cls=cls,
    )
