import operator
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from typing import (
    Any,
    Generic,
    TypeVar,
)

T = TypeVar("T")
Current = TypeVar("Current")
Desired = TypeVar("Desired")
Key = TypeVar("Key")


@dataclass(frozen=True, eq=True)
class DiffPair(Generic[Current, Desired]):
    current: Current
    desired: Desired


@dataclass(frozen=True, eq=True)
class DiffResult(Generic[Current, Desired, Key]):
    add: dict[Key, Desired]
    delete: dict[Key, Current]
    change: dict[Key, DiffPair[Current, Desired]]
    identical: dict[Key, DiffPair[Current, Desired]]


def _default_key(item: Any) -> Any:
    return item


def diff_mappings(
    current: Mapping[Key, Current],
    desired: Mapping[Key, Desired],
    equal: Callable[[Current, Desired], bool] = operator.eq,
) -> DiffResult[Current, Desired, Key]:
    """
    Compare two mappings and return a `DiffResult` instance containing the differences between them.

    :param current: The current mapping to compare.
    :type current: Mapping[Key, Current]
    :param desired: The desired mapping to compare.
    :type desired: Mapping[Key, Desired]
    :param equal: A function that compares two elements in the mappings and returns True if they are equal.
        The default behavior is to use the `==` operator.
    :type equal: Callable[[Current, Desired], bool]
    :return: A `DiffResult` instance containing the differences between the `current` and `desired` mappings,
        including elements that were added, deleted, changed or identical.
    :rtype: DiffResult[Current, Desired, Key]
    :raises: None

    Example:
        >>> current = {"i": 1, "c": 2, "d": 3}
        >>> desired = {"i": 1, "c": 20, "a": 30}
        >>> result = diff_mappings(current, desired, equal=lambda c, d: c == d)
        DiffResult(
            add={'a': 30},
            delete={'d': 3},
            change={'c': DiffPair(current=2, desired=20),
            identical={'i': DiffPair(current=1, desired=1)},
        )
    """
    add = {k: desired[k] for k in desired.keys() - current.keys()}
    delete = {k: current[k] for k in current.keys() - desired.keys()}
    change, identical = {}, {}
    for k in current.keys() & desired.keys():
        diff_pair = DiffPair(current=current[k], desired=desired[k])
        if equal(diff_pair.current, diff_pair.desired):
            identical[k] = diff_pair
        else:
            change[k] = diff_pair
    return DiffResult(
        add=add,
        delete=delete,
        change=change,
        identical=identical,
    )


def diff_any_iterables(
    current: Iterable[Current],
    desired: Iterable[Desired],
    current_key: Callable[[Current], Key] = _default_key,
    desired_key: Callable[[Desired], Key] = _default_key,
    equal: Callable[[Current, Desired], bool] = operator.eq,
) -> DiffResult[Current, Desired, Key]:
    """
    Compare two iterables and return a `DiffResult` instance containing the differences between them.

    :param current: The current iterable to compare.
    :type current: Iterable[Current]
    :param desired: The desired iterable to compare.
    :type desired: Iterable[Desired]
    :param current_key: A function that returns the key for an element in the `current` iterable.
        If not provided, the default behavior is to use the element itself as the key.
    :type current_key: Callable[[Current], Key]
    :param desired_key: A function that returns the key for an element in the `desired` iterable.
        If not provided, the default behavior is to use the element itself as the key.
    :type desired_key: Callable[[Desired], Key]
    :param equal: A function that compares two elements in the iterables and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Callable[[Current, Desired], bool]
    :return: A `DiffResult` instance containing the differences between the `current` and `desired` iterables,
        including elements that were added, deleted, changed or identical.
    :rtype: DiffResult[Current, Desired, Key]
    :raises: None

    Example:
        >>> current = [
        ...     {"name": "i", "value": 1},
        ...     {"name": "c", "value": 2},
        ...     {"name": "d", "value": 3},
        ... ]
        >>> desired = [
        ...     {"name": "i", "value": 1},
        ...     {"name": "c", "value": 20},
        ...     {"name": "a", "value": 30},
        ... ]
        >>> result = diff_any_iterables(
        ...     current,
        ...     desired,
        ...     lambda c: c["name"],
        ...     lambda d: d["name"],
        ...     equal=lambda c, d: c["value"] == d["value"],
        ... )
        DiffResult(
            add={'a': {'name': 'a', 'value': 30}},
            delete={'d': {'name': 'd', 'value': 3}},
            change={'c': DiffPair(current={'name': 'c', 'value': 2}, desired={'name': 'c', 'value': 20})),
            identical={'i': DiffPair(current={'name': 'i', 'value': 1}, desired={'name': 'i', 'value': 1})},
        )
    """
    current_dict = {current_key(c): c for c in current}
    desired_dict = {desired_key(d): d for d in desired}
    return diff_mappings(
        current_dict,
        desired_dict,
        equal=equal,
    )


def diff_iterables(
    current: Iterable[T],
    desired: Iterable[T],
    key: Callable[[T], Key] = _default_key,
    equal: Callable[[T, T], bool] = operator.eq,
) -> DiffResult[T, T, Key]:
    """
    Compare two iterables with same type and return a `DiffResult` instance containing the differences between them.

    :param current: The current iterable to compare.
    :type current: Iterable[T]
    :param desired: The desired iterable to compare.
    :type desired: Iterable[T]
    :param key: A function that returns the key for an element in the `current` and `desired` iterable.
        If not provided, the default behavior is to use the element itself as the key.
    :type key: Callable[[Current], Key]
    :param equal: A function that compares two elements in the iterables and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Callable[[Current, Desired], bool]
    :return: A `DiffResult` instance containing the differences between the `current` and `desired` iterables,
        including elements that were added, deleted, changed or identical.
    :rtype: DiffResult[T, T, Key]
    :raises: None

    Example:
        >>> current = [
        ...     {"name": "i", "value": 1},
        ...     {"name": "c", "value": 2},
        ...     {"name": "d", "value": 3},
        ... ]
        >>> desired = [
        ...     {"name": "i", "value": 1},
        ...     {"name": "c", "value": 20},
        ...     {"name": "a", "value": 30},
        ... ]
        >>> result = diff_iterables(
        ...     current,
        ...     desired,
        ...     lambda x: x["name"],
        ...     equal=lambda c, d: c["value"] == d["value"],
        ... )
        DiffResult(
            add={'a': {'name': 'a', 'value': 30}},
            delete={'d': {'name': 'd', 'value': 3}},
            change={'c': DiffPair(current={'name': 'c', 'value': 2}, desired={'name': 'c', 'value': 20})),
            identical={'i': DiffPair(current={'name': 'i', 'value': 1}, desired={'name': 'i', 'value': 1})},
        )
    """
    return diff_any_iterables(
        current,
        desired,
        current_key=key,
        desired_key=key,
        equal=equal,
    )
