from dataclasses import dataclass
from typing import Any

from reconcile.utils import differ
from reconcile.utils.differ import DiffResult


def test_diff_mappings_with_default_equal() -> None:
    current = {"i": 1, "c": 2, "d": 3}
    desired = {"i": 1, "c": 20, "a": 30}

    result = differ.diff_mappings(current, desired)

    assert result == differ.DiffResult(
        add={"a": 30},
        delete={"d": 3},
        change={"c": differ.DiffPair(2, 20)},
        identical={"i": differ.DiffPair(1, 1)},
    )


def test_diff_mappings_with_custom_equal() -> None:
    current = {"i": 1, "c": 2, "d": 3}
    desired = {"i": [1], "c": [20], "a": [30]}

    result = differ.diff_mappings(current, desired, equal=lambda c, d: c == d[0])

    assert result == differ.DiffResult(
        add={"a": [30]},
        delete={"d": 3},
        change={"c": differ.DiffPair(2, [20])},
        identical={"i": differ.DiffPair(1, [1])},
    )


def test_diff_any_iterables_with_default_equal() -> None:
    current = [
        {"name": "i", "value": 1},
        {"name": "c", "value": 2},
        {"name": "d", "value": 3},
    ]

    desired = [
        {"name": "i", "value": 1},
        {"name": "c", "value": 20},
        {"name": "a", "value": 30},
    ]

    result = differ.diff_any_iterables(
        current,
        desired,
        current_key=lambda c: c["name"],
        desired_key=lambda d: d["name"],
    )

    assert result == differ.DiffResult(
        add={
            "a": {"name": "a", "value": 30},
        },
        delete={
            "d": {"name": "d", "value": 3},
        },
        change={
            "c": differ.DiffPair(
                {"name": "c", "value": 2},
                {"name": "c", "value": 20},
            )
        },
        identical={
            "i": differ.DiffPair(
                {"name": "i", "value": 1},
                {"name": "i", "value": 1},
            )
        },
    )


def test_diff_any_iterables_with_custom_equal() -> None:
    current = [
        {"name": "i", "value": 1},
        {"name": "c", "value": 2},
        {"name": "d", "value": 3},
    ]

    desired = [
        {"name": "i", "value": [1]},
        {"name": "c", "value": [20]},
        {"name": "a", "value": [30]},
    ]

    result = differ.diff_any_iterables(
        current,
        desired,
        current_key=lambda c: c["name"],
        desired_key=lambda d: d["name"],
        equal=lambda c, d: c["value"] == d["value"][0],
    )

    assert result == differ.DiffResult(
        add={
            "a": {"name": "a", "value": [30]},
        },
        delete={
            "d": {"name": "d", "value": 3},
        },
        change={
            "c": differ.DiffPair(
                {"name": "c", "value": 2},
                {"name": "c", "value": [20]},
            )
        },
        identical={
            "i": differ.DiffPair(
                {"name": "i", "value": 1},
                {"name": "i", "value": [1]},
            )
        },
    )


def test_diff_any_iterables_with_scalar_types() -> None:
    current = ["i", "d"]
    desired = ["i", "a"]
    result = differ.diff_any_iterables(current, desired)  # type: ignore

    assert result == differ.DiffResult(
        add={"a": "a"},
        delete={"d": "d"},
        change={},
        identical={"i": differ.DiffPair("i", "i")},
    )


@dataclass
class Foo:
    name: str
    value: int

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Foo):
            return False

        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)


def test_diff_any_iterables_with_custom_types() -> None:
    current = [
        Foo(name="i", value=1),
        Foo(name="d", value=2),
    ]
    desired = [
        Foo(name="i", value=10),
        Foo(name="a", value=30),
    ]

    result: DiffResult[Foo, Foo, Foo] = differ.diff_any_iterables(current, desired)

    assert len(result.add) == 1
    assert result.add[Foo(name="a", value=30)].name == "a"
    assert result.add[Foo(name="a", value=30)].value == 30

    assert len(result.delete) == 1
    assert result.delete[Foo(name="d", value=2)].name == "d"
    assert result.delete[Foo(name="d", value=2)].value == 2

    assert len(result.change) == 0

    assert len(result.identical) == 1
    assert result.identical[Foo(name="i", value=10)].current.name == "i"
    assert result.identical[Foo(name="i", value=10)].current.value == 1
    assert result.identical[Foo(name="i", value=10)].desired.name == "i"
    assert result.identical[Foo(name="i", value=10)].desired.value == 10


def test_diff_iterables() -> None:
    current = [
        {"name": "i", "value": 1},
        {"name": "c", "value": 2},
        {"name": "d", "value": 3},
    ]

    desired = [
        {"name": "i", "value": 1},
        {"name": "c", "value": 20},
        {"name": "a", "value": 30},
    ]

    result = differ.diff_iterables(
        current,
        desired,
        key=lambda x: x["name"],
    )

    assert result == differ.DiffResult(
        add={
            "a": {"name": "a", "value": 30},
        },
        delete={
            "d": {"name": "d", "value": 3},
        },
        change={
            "c": differ.DiffPair(
                {"name": "c", "value": 2},
                {"name": "c", "value": 20},
            ),
        },
        identical={
            "i": differ.DiffPair(
                {"name": "i", "value": 1},
                {"name": "i", "value": 1},
            ),
        },
    )
