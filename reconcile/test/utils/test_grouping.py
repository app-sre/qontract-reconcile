from dataclasses import dataclass
from typing import (
    Callable,
    Iterable,
    TypeVar,
)

import pytest

from reconcile.utils.grouping import group_by

ElementType = TypeVar("ElementType")
KeyType = TypeVar("KeyType")


@dataclass
class Fruit:
    name: str
    color: str


@pytest.mark.parametrize(
    "iterable,key,expected",
    [
        # group simple items
        (
            ["apple", "ananas", "banana"],
            lambda fruit: fruit[0],
            {"a": ["apple", "ananas"], "b": ["banana"]},
        ),
        # group objects
        (
            [
                Fruit("apple", "red"),
                Fruit("banana", "yellow"),
                Fruit("grapes", "yellow"),
            ],
            lambda fruit: fruit.color,
            {
                "red": [Fruit("apple", "red")],
                "yellow": [Fruit("banana", "yellow"), Fruit("grapes", "yellow")],
            },
        ),
    ],
)
def test_group_by(
    iterable: Iterable[ElementType],
    key: Callable[[ElementType], KeyType],
    expected: dict[KeyType, list[ElementType]],
):
    assert group_by(iterable, key) == expected
