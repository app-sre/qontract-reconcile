import operator
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pytest

from reconcile.utils.grouping import group_by


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
            operator.itemgetter(0),
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
def test_group_by[ElementType, KeyType](
    iterable: Iterable[ElementType],
    key: Callable[[ElementType], KeyType],
    expected: dict[KeyType, list[ElementType]],
) -> None:
    assert group_by(iterable, key) == expected
