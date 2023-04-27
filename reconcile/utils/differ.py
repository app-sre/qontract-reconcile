from collections.abc import (
    Callable,
    Mapping,
)
from dataclasses import dataclass
from typing import (
    Generic,
    Optional,
    TypeVar,
)

C = TypeVar("C")
D = TypeVar("D")
K = TypeVar("K")


@dataclass(frozen=True, eq=True)
class DiffResult(Generic[C, D, K]):
    add: dict[K, D]
    delete: dict[K, C]
    change: dict[K, tuple[C, D]]


def diff(
    current: Mapping[K, C],
    desired: Mapping[K, D],
    equal: Optional[Callable[[C, D], bool]] = None,
) -> DiffResult[C, D, K]:
    """
    Compare two mappings and return a `DiffResult` instance containing the differences between them.

    :param current: The current mapping to compare.
    :type current: Mapping[K, C]
    :param desired: The desired mapping to compare.
    :type desired: Mapping[K, D]
    :param equal: An optional function that compares two elements in the mappings and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[C, D], bool]]
    :return: A `DiffResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added, deleted, or changed.
    :rtype: DiffResult[C, D, K]
    :raises: None
    """
    eq = equal or (lambda x, y: x == y)
    add = {k: desired[k] for k in desired.keys() - current.keys()}
    delete = {k: current[k] for k in current.keys() - desired.keys()}
    change = {
        k: (current[k], desired[k])
        for k in current.keys() & desired.keys()
        if not eq(current[k], desired[k])
    }
    return DiffResult(add=add, delete=delete, change=change)
