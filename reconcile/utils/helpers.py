import logging
import random
import re
import string
from collections import Counter
from collections.abc import (
    Iterable,
    Mapping,
)
from contextlib import contextmanager
from typing import (
    Any,
    TypeVar,
)

DEFAULT_TOGGLE_LEVEL = logging.ERROR


@contextmanager
def toggle_logger(log_level: int = DEFAULT_TOGGLE_LEVEL):
    logger = logging.getLogger()
    default_level = logger.level
    try:
        yield logger.setLevel(log_level)  # type: ignore[func-returns-value]
    finally:
        logger.setLevel(default_level)


# Copied with love from https://stackoverflow.com/questions/6027558
def flatten(
    d: Mapping[str, Any], parent_key: str = "", sep: str = "."
) -> dict[str, str]:
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        if v is None:
            continue
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, Mapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, str(v)))
    return dict(items)


Item = TypeVar("Item")


def find_duplicates(items: Iterable[Item]) -> list[Item]:
    return [item for item, count in Counter(items).items() if count > 1]


def generate_random_password(string_length: int = 20) -> str:
    """Generate a random string of letters and digits"""
    letters_and_digits = string.ascii_letters + string.digits
    return "".join(random.choices(letters_and_digits, k=string_length))


def match_patterns(patterns: Iterable[str], s: str) -> bool:
    """
    Check if any pattern matches the string.
    :param patterns: patterns to match
    :param s: string to check
    :return: True if any pattern matches, False otherwise
    """
    return any(re.match(p, s) for p in patterns)
