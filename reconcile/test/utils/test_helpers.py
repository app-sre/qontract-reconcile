import logging
from collections.abc import (
    Iterable,
    Sequence,
)
from typing import Any

import pytest

from reconcile.utils.helpers import (
    DEFAULT_TOGGLE_LEVEL,
    find_duplicates,
    flatten,
    toggle_logger,
)


@pytest.fixture
def default_level():
    default_level = logging.INFO
    assert default_level != DEFAULT_TOGGLE_LEVEL

    return default_level


@pytest.fixture
def custom_level(default_level):
    custom_level = logging.WARNING
    assert custom_level != default_level
    assert custom_level != DEFAULT_TOGGLE_LEVEL

    return custom_level


@pytest.fixture
def logger(default_level):
    logger = logging.getLogger()
    logger.level = default_level
    assert logger.level == default_level

    return logger


def test_toggle_logger_default_toggle_level(logger, default_level):
    with toggle_logger():
        assert logger.level == DEFAULT_TOGGLE_LEVEL

    assert logger.level == default_level


def test_toggle_logger_custom_level(logger, custom_level, default_level):
    with toggle_logger(custom_level):
        assert logger.level == custom_level

    assert logger.level == default_level


def test_toggle_logger_default_level(logger, default_level):
    with toggle_logger(default_level):
        assert logger.level == default_level

    assert logger.level == default_level


@pytest.mark.parametrize(
    "input_dict, expected, sep",
    [
        ({"a": 1, "b": {"c": 2}}, {"a": "1", "b.c": "2"}, "."),
        ({"a": 1, "b": {"c": 2}}, {"a": "1", "b/c": "2"}, "/"),
        ({"a": 1, "b": {"c": [1, 2, 3]}}, {"a": "1", "b.c": "[1, 2, 3]"}, "."),
        (
            {"a": 1, "b": {"c": {"d": "foobar"}}, "la": {"le": "lu"}},
            {"a": "1", "b.c.d": "foobar", "la.le": "lu"},
            ".",
        ),
    ],
)
def test_flatten(input_dict: dict, expected: dict, sep: str) -> None:
    assert flatten(input_dict, sep=sep) == expected


@pytest.mark.parametrize(
    "items, expected",
    [
        # integers
        ([1, 2, 3, 4, 5], []),
        ([1, 2, 3, 4, 5, 1], [1]),
        ([1, 2, 3, 4, 5, 1, 2], [1, 2]),
        # strings
        (["a", "b", "c", "d", "e"], []),
        (["a", "b", "c", "d", "e", "a"], ["a"]),
        (["a", "b", "c", "d", "e", "a", "b"], ["a", "b"]),
        # mixed
        ([1, 2, 3, 4, 5, "a", "b", "c", "d", "e"], []),
        ([1, 2, 3, 4, 5, "a", "b", "c", "d", "e", 1], [1]),
        ([1, 2, 3, 4, 5, "a", "b", "c", "d", "e", 1, "a"], [1, "a"]),
    ],
)
def test_find_duplicates(items: Iterable[Any], expected: Sequence[Any]) -> None:
    assert find_duplicates(items) == expected
