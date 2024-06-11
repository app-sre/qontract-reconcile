from collections import defaultdict
from typing import (
    TypeVar,
)
from collections.abc import Callable, Hashable, Iterable

ElementType = TypeVar("ElementType")
KeyType = TypeVar("KeyType", bound=Hashable)


def group_by(
    iterable: Iterable[ElementType], key: Callable[[ElementType], KeyType]
) -> dict[KeyType, list[ElementType]]:
    groups = defaultdict(list)
    for item in iterable:
        groups[key(item)].append(item)
    return groups
