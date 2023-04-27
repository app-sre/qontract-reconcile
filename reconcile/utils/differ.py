from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    Sequence,
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
class DiffKeyedResult(Generic[C, D, K]):
    add: dict[K, D]
    delete: dict[K, C]
    change: dict[K, tuple[C, D]]


@dataclass(frozen=True, eq=True)
class DiffListsResult(Generic[C, D]):
    add: list[D]
    delete: list[C]
    identical: list[tuple[C, D]]


def diff_mappings(
    current: Mapping[K, C],
    desired: Mapping[K, D],
    equal: Optional[Callable[[C, D], bool]] = None,
) -> DiffKeyedResult[C, D, K]:
    """
    Compare two mappings and return a `DiffKeyedResult` instance containing the differences between them.

    :param current: The current mapping to compare.
    :type current: Mapping[K, C]
    :param desired: The desired mapping to compare.
    :type desired: Mapping[K, D]
    :param equal: An optional function that compares two elements in the mappings and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[C, D], bool]]
    :return: A `DiffResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added, deleted, or changed.
    :rtype: DiffKeyedResult[C, D, K]
    :raises: None

    Example:
        >>> current = {"a": 1, "b": 2, "c": 3}
        >>> desired = {"a": 1, "b": 20, "d": 30}
        >>> result = diff_mappings(current, desired, equal=lambda c, d: c == d)
        DiffKeyedResult(add={'d': 30}, delete={'c': 3}, change={'b': (2, 20)})
    """
    eq = equal or (lambda c, d: c == d)
    add = {k: desired[k] for k in desired.keys() - current.keys()}
    delete = {k: current[k] for k in current.keys() - desired.keys()}
    change = {
        k: (current[k], desired[k])
        for k in current.keys() & desired.keys()
        if not eq(current[k], desired[k])
    }
    return DiffKeyedResult(add=add, delete=delete, change=change)


def diff_by_key(
    current: Iterable[C],
    desired: Iterable[D],
    current_key: Callable[[C], K],
    desired_key: Callable[[D], K],
    equal: Optional[Callable[[C, D], bool]] = None,
) -> DiffKeyedResult[C, D, K]:
    """
    Compare two iterables and return a `DiffKeyedResult` instance containing the differences between them.

    :param current: The current iterable to compare.
    :type current: Iterable[C]
    :param desired: The desired iterable to compare.
    :type desired: Iterable[D]
    :param current_key: A function that returns the key for an element in the `current` iterable.
    :type current_key: Callable[[C], K]
    :param desired_key: A function that returns the key for an element in the `desired` iterable.
    :type desired_key: Callable[[D], K]
    :param equal: An optional function that compares two elements in the iterables and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[C, D], bool]]
    :return: A `DiffKeyedResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added, deleted, or changed.
    :rtype: DiffKeyedResult[C, D, K]
    :raises: None

    Example:
    >>> current = [
    ...     {"name": "a", "value": 1},
    ...     {"name": "b", "value": 2},
    ...     {"name": "c", "value": 3},
    ... ]
    >>> desired = [
    ...     {"name": "a", "value": 1},
    ...     {"name": "b", "value": 20},
    ...     {"name": "d", "value": 30},
    ... ]
    >>> result = diff_by_key(
    ...     current,
    ...     desired,
    ...     lambda c: c["name"],
    ...     lambda d: d["name"],
    ...     equal=lambda c, d: c["value"] == d["value"],
    ... )
    DiffKeyedResult(
        add={'d': {'name': 'd', 'value': 30}},
        delete={'c': {'name': 'c', 'value': 3}},
        change={'b': ({'name': 'b', 'value': 2}, {'name': 'b', 'value': 20}))
    )
    """
    current_dict = {current_key(x): x for x in current}
    desired_dict = {desired_key(x): x for x in desired}
    return diff_mappings(current_dict, desired_dict, equal=equal)


def diff_lists(
    current: Sequence[C],
    desired: Sequence[D],
) -> DiffListsResult[C, D]:
    """
    Compare two iterables and return a `DiffListsResult` instance containing the differences between them.

    :param current: The current sequence to compare.
    :type current: Sequence[C]
    :param desired: The desired sequence to compare.
    :type desired: Sequence[D]
    :return: A `DiffListsResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added ,deleted or identical.
    :rtype: DiffListsResult[C, D]
    :raises: None

    Example:
    >>> current = [1, 2]
    >>> desired = [1, 3]
    >>> result = diff_lists(current, desired)
    DiffListsResult(add=[3], delete=[2], identical=[(1, 1)])
    """
    current_with_index = {x: idx for idx, x in enumerate(current)}
    desired_with_index = {x: idx for idx, x in enumerate(desired)}
    add = list(desired_with_index.keys() - current_with_index.keys())
    delete = list(current_with_index.keys() - desired_with_index.keys())
    identical = [
        (current[current_with_index[k]], desired[desired_with_index[k]])
        for k in current_with_index.keys() & desired_with_index.keys()
    ]
    return DiffListsResult(
        add=add,
        delete=delete,
        identical=identical,
    )
