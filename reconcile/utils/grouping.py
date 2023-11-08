from collections import defaultdict
from typing import (
    Callable,
    Hashable,
    Iterable,
    TypeVar,
)

ElementType = TypeVar("ElementType")
KeyType = TypeVar("KeyType", bound=Hashable)


def group_by(
    iterable: Iterable[ElementType], key: Callable[[ElementType], KeyType]
) -> dict[KeyType, list[ElementType]]:
    groups = defaultdict(list)
    for item in iterable:
        groups[key(item)].append(item)
    return groups
