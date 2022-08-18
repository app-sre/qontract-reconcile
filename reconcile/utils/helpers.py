import logging

from contextlib import contextmanager
from typing import Any, Iterable, Optional


DEFAULT_TOGGLE_LEVEL = logging.ERROR


@contextmanager
def toggle_logger(log_level: int = DEFAULT_TOGGLE_LEVEL):
    logger = logging.getLogger()
    default_level = logger.level
    try:
        yield logger.setLevel(log_level)  # type: ignore[func-returns-value]
    finally:
        logger.setLevel(default_level)


def filter_null(arr: Optional[Iterable[Any]]) -> list[Any]:
    """
    GQL is null by default. Once we harden our schema with
    more NonNull types, we can reduce the number
    of callers of this function.

    This function can be removed, when our schema only allows
    non-nullable lists: [Obj!]!
    """
    return [a for a in arr or [] if a]
