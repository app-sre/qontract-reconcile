from dataclasses import dataclass

from reconcile.utils import differ


def test_diff_mappings_with_default_equal():
    current = {"a": 1, "b": 2, "c": 3}
    desired = {"a": 1, "b": 20, "d": 30}

    result = differ.diff_mappings(current, desired)

    assert result == differ.DiffKeyedResult(
        add={"d": 30},
        delete={"c": 3},
        change={"b": (2, 20)},
    )


def test_diff_mappings_with_custom_equal():
    current = {"a": 1, "b": 2, "c": 3}
    desired = {"a": [1], "b": [20], "d": [30]}

    result = differ.diff_mappings(current, desired, equal=lambda c, d: c == d[0])

    assert result == differ.DiffKeyedResult(
        add={"d": [30]},
        delete={"c": 3},
        change={"b": (2, [20])},
    )


def test_diff_by_key_with_default_equal():
    current = [
        {"name": "a", "value": 1},
        {"name": "b", "value": 2},
        {"name": "c", "value": 3},
    ]

    desired = [
        {"name": "a", "value": 1},
        {"name": "b", "value": 20},
        {"name": "d", "value": 30},
    ]

    result = differ.diff_by_key(
        current,
        desired,
        current_key=lambda c: c["name"],
        desired_key=lambda d: d["name"],
    )

    assert result == differ.DiffKeyedResult(
        add={
            "d": {"name": "d", "value": 30},
        },
        delete={
            "c": {"name": "c", "value": 3},
        },
        change={
            "b": (
                {"name": "b", "value": 2},
                {"name": "b", "value": 20},
            )
        },
    )


def test_diff_by_key_with_custom_equal():
    current = [
        {"name": "a", "value": 1},
        {"name": "b", "value": 2},
        {"name": "c", "value": 3},
    ]

    desired = [
        {"name": "a", "value": [1]},
        {"name": "b", "value": [20]},
        {"name": "d", "value": [30]},
    ]

    result = differ.diff_by_key(
        current,
        desired,
        current_key=lambda c: c["name"],
        desired_key=lambda d: d["name"],
        equal=lambda c, d: c["value"] == d["value"][0],
    )

    assert result == differ.DiffKeyedResult(
        add={
            "d": {"name": "d", "value": [30]},
        },
        delete={
            "c": {"name": "c", "value": 3},
        },
        change={
            "b": (
                {"name": "b", "value": 2},
                {"name": "b", "value": [20]},
            )
        },
    )


def test_diff_lists_with_scalar_types():
    current = ["a", "b"]
    desired = ["a", "c"]

    result = differ.diff_lists(current, desired)

    assert result == differ.DiffListsResult(
        add=["c"],
        delete=["b"],
        identical=[("a", "a")],
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


def test_diff_lists_with_custom_types():
    current = [
        Foo(name="a", value=1),
        Foo(name="b", value=2),
    ]
    desired = [
        Foo(name="a", value=10),
        Foo(name="c", value=30),
    ]

    result = differ.diff_lists(current, desired)

    assert len(result.add) == 1
    assert result.add[0].name == "c"
    assert result.add[0].value == 30

    assert len(result.delete) == 1
    assert result.delete[0].name == "b"
    assert result.delete[0].value == 2

    assert len(result.identical) == 1
    assert result.identical[0][0].name == "a"
    assert result.identical[0][0].value == 1
    assert result.identical[0][1].name == "a"
    assert result.identical[0][1].value == 10
