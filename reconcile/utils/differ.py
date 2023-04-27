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
    cast,
)

Current = TypeVar("Current")
Desired = TypeVar("Desired")
Key = TypeVar("Key")


@dataclass(frozen=True, eq=True)
class DiffKeyedResult(Generic[Current, Desired, Key]):
    add: dict[Key, Desired]
    delete: dict[Key, Current]
    change: dict[Key, tuple[Current, Desired]]


@dataclass(frozen=True, eq=True)
class DiffListsResult(Generic[Current, Desired]):
    add: list[Desired]
    delete: list[Current]
    identical: list[tuple[Current, Desired]]


def diff_mappings(
    current: Mapping[Key, Current],
    desired: Mapping[Key, Desired],
    equal: Optional[Callable[[Current, Desired], bool]] = None,
) -> DiffKeyedResult[Current, Desired, Key]:
    """
    Compare two mappings and return a `DiffKeyedResult` instance containing the differences between them.

    :param current: The current mapping to compare.
    :type current: Mapping[Key, Current]
    :param desired: The desired mapping to compare.
    :type desired: Mapping[Key, Desired]
    :param equal: An optional function that compares two elements in the mappings and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[Current, Desired], bool]]
    :return: A `DiffResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added, deleted, or changed.
    :rtype: DiffKeyedResult[Current, Desired, Key]
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
    current: Iterable[Current],
    desired: Iterable[Desired],
    current_key: Callable[[Current], Key],
    desired_key: Callable[[Desired], Key],
    equal: Optional[Callable[[Current, Desired], bool]] = None,
) -> DiffKeyedResult[Current, Desired, Key]:
    """
    Compare two iterables and return a `DiffKeyedResult` instance containing the differences between them.

    :param current: The current iterable to compare.
    :type current: Iterable[Current]
    :param desired: The desired iterable to compare.
    :type desired: Iterable[Desired]
    :param current_key: A function that returns the key for an element in the `current` iterable.
    :type current_key: Callable[[Current], Key]
    :param desired_key: A function that returns the key for an element in the `desired` iterable.
    :type desired_key: Callable[[Desired], Key]
    :param equal: An optional function that compares two elements in the iterables and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[Current, Desired], bool]]
    :return: A `DiffKeyedResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added, deleted, or changed.
    :rtype: DiffKeyedResult[Current, Desired, Key]
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
    current_dict = {current_key(c): c for c in current}
    desired_dict = {desired_key(d): d for d in desired}
    return diff_mappings(current_dict, desired_dict, equal=equal)


def diff_lists(
    current: Sequence[Current],
    desired: Sequence[Desired],
) -> DiffListsResult[Current, Desired]:
    """
    Compare two iterables and return a `DiffListsResult` instance containing the differences between them.

    :param current: The current sequence to compare.
    :type current: Sequence[Current]
    :param desired: The desired sequence to compare.
    :type desired: Sequence[Desired]
    :return: A `DiffListsResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added ,deleted or identical.
    :rtype: DiffListsResult[Current, Desired]
    :raises: None

    Example:
    >>> current = [1, 2]
    >>> desired = [1, 3]
    >>> result = diff_lists(current, desired)
    DiffListsResult(add=[3], delete=[2], identical=[(1, 1)])
    """
    current_to_index = {c: idx for idx, c in enumerate(current)}
    desired_to_index = {d: idx for idx, d in enumerate(desired)}
    add = list(desired_to_index.keys() - current_to_index.keys())
    delete = list(current_to_index.keys() - desired_to_index.keys())
    identical = [
        (
            current[current_to_index[cast(Current, k)]],
            desired[desired_to_index[cast(Desired, k)]],
        )
        for k in current_to_index.keys() & desired_to_index.keys()
    ]
    return DiffListsResult(add=add, delete=delete, identical=identical)
