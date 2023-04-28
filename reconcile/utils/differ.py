from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from typing import (
    Generic,
    Optional,
    TypeVar,
    cast,
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


def _default_equal(current: Current, desired: Desired) -> bool:
    return current == desired


def _default_current_key(current: Current) -> Key:
    return cast(Key, current)


def _default_desired_key(desired: Desired) -> Key:
    return cast(Key, desired)


def diff_mappings(
    current: Mapping[Key, Current],
    desired: Mapping[Key, Desired],
    equal: Optional[Callable[[Current, Desired], bool]] = None,
) -> DiffResult[Current, Desired, Key]:
    """
    Compare two mappings and return a `DiffResult` instance containing the differences between them.

    :param current: The current mapping to compare.
    :type current: Mapping[Key, Current]
    :param desired: The desired mapping to compare.
    :type desired: Mapping[Key, Desired]
    :param equal: An optional function that compares two elements in the mappings and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[Current, Desired], bool]]
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
    if equal is None:
        equal = _default_equal
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
    current_key: Optional[Callable[[Current], Key]] = None,
    desired_key: Optional[Callable[[Desired], Key]] = None,
    equal: Optional[Callable[[Current, Desired], bool]] = None,
) -> DiffResult[Current, Desired, Key]:
    """
    Compare two iterables and return a `DiffResult` instance containing the differences between them.

    :param current: The current iterable to compare.
    :type current: Iterable[Current]
    :param desired: The desired iterable to compare.
    :type desired: Iterable[Desired]
    :param current_key: An optional function that returns the key for an element in the `current` iterable.
        If not provided, the default behavior is to use the element itself as the key.
    :type current_key: Optional[Callable[[Current], Key]]
    :param desired_key: An optaionl function that returns the key for an element in the `desired` iterable.
        If not provided, the default behavior is to use the element itself as the key.
    :type desired_key: Optional[Callable[[Desired], Key]]
    :param equal: An optional function that compares two elements in the iterables and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[Current, Desired], bool]]
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
    if current_key is None:
        current_key = _default_current_key
    if desired_key is None:
        desired_key = _default_desired_key
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
    key: Optional[Callable[[T], Key]] = None,
    equal: Optional[Callable[[T, T], bool]] = None,
) -> DiffResult[T, T, Key]:
    """
    Compare two iterables with same type and return a `DiffResult` instance containing the differences between them.
    :param current: The current iterable to compare.
    :type current: Iterable[T]
    :param desired: The desired iterable to compare.
    :type desired: Iterable[T]
    :param key: An optional function that returns the key for an element in the `current` and `desired` iterable.
        If not provided, the default behavior is to use the element itself as the key.
    :type key: Optional[Callable[[Current], Key]]
    :param equal: An optional function that compares two elements in the iterables and returns True if they are equal.
        If not provided, the default behavior is to use the `==` operator.
    :type equal: Optional[Callable[[Current, Desired], bool]]
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
