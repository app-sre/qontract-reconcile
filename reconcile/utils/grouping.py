from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable


def group_by[ElementType, KeyType: Hashable](
    iterable: Iterable[ElementType], key: Callable[[ElementType], KeyType]
) -> dict[KeyType, list[ElementType]]:
    groups = defaultdict(list)
    for item in iterable:
        groups[key(item)].append(item)
    return groups
