"""Unit tests for differ module.

Tests DiffPair, DiffResult, and diff functions for comparing mappings and iterables.
"""

import operator
from dataclasses import dataclass

import pytest
from qontract_utils.differ import (
    DiffPair,
    DiffResult,
    diff_any_iterables,
    diff_iterables,
    diff_mappings,
)


class TestDiffPair:
    """Test DiffPair dataclass."""

    def test_diff_pair_creation(self) -> None:
        """Test creating a DiffPair."""
        pair = DiffPair(current=1, desired=2)
        assert pair.current == 1
        assert pair.desired == 2

    def test_diff_pair_equality(self) -> None:
        """Test DiffPair equality comparison."""
        pair1 = DiffPair(current=1, desired=2)
        pair2 = DiffPair(current=1, desired=2)
        pair3 = DiffPair(current=1, desired=3)

        assert pair1 == pair2
        assert pair1 != pair3

    def test_diff_pair_frozen(self) -> None:
        """Test that DiffPair is immutable."""
        pair = DiffPair(current=1, desired=2)

        with pytest.raises(AttributeError):
            pair.current = 3  # type: ignore[misc]


class TestDiffResult:
    """Test DiffResult dataclass."""

    def test_diff_result_creation(self) -> None:
        """Test creating a DiffResult."""
        result = DiffResult(
            add={"a": 1},
            delete={"b": 2},
            change={"c": DiffPair(current=3, desired=4)},
            identical={"d": DiffPair(current=5, desired=5)},
        )

        assert result.add == {"a": 1}
        assert result.delete == {"b": 2}
        assert result.change == {"c": DiffPair(current=3, desired=4)}
        assert result.identical == {"d": DiffPair(current=5, desired=5)}

    def test_diff_result_frozen(self) -> None:
        """Test that DiffResult is immutable."""
        result: DiffResult[int, int, str] = DiffResult(
            add={}, delete={}, change={}, identical={}
        )

        with pytest.raises(AttributeError):
            result.add = {"a": 1}  # type: ignore[misc]


class TestDiffMappings:
    """Test diff_mappings function."""

    def test_diff_mappings_identical(self) -> None:
        """Test diff_mappings with identical mappings."""
        current = {"a": 1, "b": 2, "c": 3}
        desired = {"a": 1, "b": 2, "c": 3}

        result = diff_mappings(current, desired)

        assert result.add == {}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {
            "a": DiffPair(current=1, desired=1),
            "b": DiffPair(current=2, desired=2),
            "c": DiffPair(current=3, desired=3),
        }

    def test_diff_mappings_add_only(self) -> None:
        """Test diff_mappings with only additions."""
        current = {"a": 1}
        desired = {"a": 1, "b": 2, "c": 3}

        result = diff_mappings(current, desired)

        assert result.add == {"b": 2, "c": 3}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {"a": DiffPair(current=1, desired=1)}

    def test_diff_mappings_delete_only(self) -> None:
        """Test diff_mappings with only deletions."""
        current = {"a": 1, "b": 2, "c": 3}
        desired = {"a": 1}

        result = diff_mappings(current, desired)

        assert result.add == {}
        assert result.delete == {"b": 2, "c": 3}
        assert result.change == {}
        assert result.identical == {"a": DiffPair(current=1, desired=1)}

    def test_diff_mappings_change_only(self) -> None:
        """Test diff_mappings with only changes."""
        current = {"a": 1, "b": 2}
        desired = {"a": 10, "b": 20}

        result = diff_mappings(current, desired)

        assert result.add == {}
        assert result.delete == {}
        assert result.change == {
            "a": DiffPair(current=1, desired=10),
            "b": DiffPair(current=2, desired=20),
        }
        assert result.identical == {}

    def test_diff_mappings_mixed_operations(self) -> None:
        """Test diff_mappings with add, delete, change, and identical elements."""
        current = {"i": 1, "c": 2, "d": 3}
        desired = {"i": 1, "c": 20, "a": 30}

        result = diff_mappings(current, desired)

        assert result.add == {"a": 30}
        assert result.delete == {"d": 3}
        assert result.change == {"c": DiffPair(current=2, desired=20)}
        assert result.identical == {"i": DiffPair(current=1, desired=1)}

    def test_diff_mappings_empty_current(self) -> None:
        """Test diff_mappings with empty current mapping."""
        current: dict[str, int] = {}
        desired = {"a": 1, "b": 2}

        result = diff_mappings(current, desired)

        assert result.add == {"a": 1, "b": 2}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {}

    def test_diff_mappings_empty_desired(self) -> None:
        """Test diff_mappings with empty desired mapping."""
        current = {"a": 1, "b": 2}
        desired: dict[str, int] = {}

        result = diff_mappings(current, desired)

        assert result.add == {}
        assert result.delete == {"a": 1, "b": 2}
        assert result.change == {}
        assert result.identical == {}

    def test_diff_mappings_both_empty(self) -> None:
        """Test diff_mappings with both mappings empty."""
        current: dict[str, int] = {}
        desired: dict[str, int] = {}

        result = diff_mappings(current, desired)

        assert result.add == {}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {}

    def test_diff_mappings_custom_equal_function(self) -> None:
        """Test diff_mappings with custom equality function."""
        current = {"a": "hello", "b": "world"}
        desired = {"a": "HELLO", "b": "WORLD"}

        # Case-insensitive comparison
        result = diff_mappings(
            current, desired, equal=lambda c, d: c.lower() == d.lower()
        )

        assert result.add == {}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {
            "a": DiffPair(current="hello", desired="HELLO"),
            "b": DiffPair(current="world", desired="WORLD"),
        }

    def test_diff_mappings_different_types(self) -> None:
        """Test diff_mappings with different value types."""
        current = {"a": 1, "b": 2}
        desired = {"a": "1", "b": "2"}

        result = diff_mappings(current, desired)

        assert result.add == {}
        assert result.delete == {}
        assert result.change == {
            "a": DiffPair(current=1, desired="1"),
            "b": DiffPair(current=2, desired="2"),
        }
        assert result.identical == {}


class TestDiffAnyIterables:
    """Test diff_any_iterables function."""

    def test_diff_any_iterables_with_dicts(self) -> None:
        """Test diff_any_iterables with list of dictionaries."""
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

        result = diff_any_iterables(
            current,
            desired,
            current_key=operator.itemgetter("name"),
            desired_key=operator.itemgetter("name"),
            equal=lambda c, d: c["value"] == d["value"],
        )

        assert result.add == {"a": {"name": "a", "value": 30}}
        assert result.delete == {"d": {"name": "d", "value": 3}}
        assert result.change == {
            "c": DiffPair(
                current={"name": "c", "value": 2}, desired={"name": "c", "value": 20}
            )
        }
        assert result.identical == {
            "i": DiffPair(
                current={"name": "i", "value": 1}, desired={"name": "i", "value": 1}
            )
        }

    def test_diff_any_iterables_with_dataclasses(self) -> None:
        """Test diff_any_iterables with dataclasses."""

        @dataclass
        class User:
            id: int
            name: str

        current = [User(1, "Alice"), User(2, "Bob")]
        desired = [User(1, "Alice Updated"), User(3, "Charlie")]

        result = diff_any_iterables(
            current,
            desired,
            current_key=lambda u: u.id,
            desired_key=lambda u: u.id,
            equal=lambda c, d: c.name == d.name,
        )

        assert result.add == {3: User(3, "Charlie")}
        assert result.delete == {2: User(2, "Bob")}
        assert result.change == {
            1: DiffPair(current=User(1, "Alice"), desired=User(1, "Alice Updated"))
        }
        assert result.identical == {}

    def test_diff_any_iterables_default_key(self) -> None:
        """Test diff_any_iterables with default key function."""
        current = [1, 2, 3]
        desired = [1, 2, 4]

        result: DiffResult[int, int, int] = diff_any_iterables(current, desired)

        assert result.add == {4: 4}
        assert result.delete == {3: 3}
        assert result.change == {}
        assert result.identical == {
            1: DiffPair(current=1, desired=1),
            2: DiffPair(current=2, desired=2),
        }

    def test_diff_any_iterables_empty_lists(self) -> None:
        """Test diff_any_iterables with empty iterables."""
        current: list[dict[str, int]] = []
        desired: list[dict[str, int]] = []

        result: DiffResult[dict[str, int], dict[str, int], int] = diff_any_iterables(
            current,
            desired,
            current_key=operator.itemgetter("name"),
            desired_key=operator.itemgetter("name"),
        )

        assert result.add == {}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {}


class TestDiffIterables:
    """Test diff_iterables function."""

    def test_diff_iterables_with_dicts(self) -> None:
        """Test diff_iterables with list of dictionaries."""
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

        result = diff_iterables(
            current,
            desired,
            key=operator.itemgetter("name"),
            equal=lambda c, d: c["value"] == d["value"],
        )

        assert result.add == {"a": {"name": "a", "value": 30}}
        assert result.delete == {"d": {"name": "d", "value": 3}}
        assert result.change == {
            "c": DiffPair(
                current={"name": "c", "value": 2}, desired={"name": "c", "value": 20}
            )
        }
        assert result.identical == {
            "i": DiffPair(
                current={"name": "i", "value": 1}, desired={"name": "i", "value": 1}
            )
        }

    def test_diff_iterables_with_strings(self) -> None:
        """Test diff_iterables with lists of strings."""
        current = ["alice", "bob", "charlie"]
        desired = ["alice", "bob", "dave"]

        result: DiffResult[str, str, str] = diff_iterables(current, desired)

        assert result.add == {"dave": "dave"}
        assert result.delete == {"charlie": "charlie"}
        assert result.change == {}
        assert result.identical == {
            "alice": DiffPair(current="alice", desired="alice"),
            "bob": DiffPair(current="bob", desired="bob"),
        }

    def test_diff_iterables_default_key(self) -> None:
        """Test diff_iterables with default key function."""
        current = [1, 2, 3]
        desired = [2, 3, 4]

        result: DiffResult[int, int, int] = diff_iterables(current, desired)

        assert result.add == {4: 4}
        assert result.delete == {1: 1}
        assert result.change == {}
        assert result.identical == {
            2: DiffPair(current=2, desired=2),
            3: DiffPair(current=3, desired=3),
        }

    def test_diff_iterables_custom_equal(self) -> None:
        """Test diff_iterables with custom equality function."""
        current = ["hello", "world"]
        desired = ["HELLO", "WORLD"]

        # When using default key function (element itself), "hello" != "HELLO" as keys
        # So this creates add/delete, not identical. Need to provide a key function.
        result = diff_iterables(
            current,
            desired,
            key=lambda x: x.lower(),  # Use lowercase as key
            equal=lambda c, d: c.lower() == d.lower(),
        )

        assert result.add == {}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {
            "hello": DiffPair(current="hello", desired="HELLO"),
            "world": DiffPair(current="world", desired="WORLD"),
        }

    def test_diff_iterables_with_dataclasses(self) -> None:
        """Test diff_iterables with dataclasses."""

        @dataclass
        class Config:
            key: str
            value: int

        current = [Config("a", 1), Config("b", 2)]
        desired = [Config("a", 1), Config("b", 20), Config("c", 3)]

        result = diff_iterables(
            current,
            desired,
            key=lambda x: x.key,
            equal=lambda c, d: c.value == d.value,
        )

        assert result.add == {"c": Config("c", 3)}
        assert result.delete == {}
        assert result.change == {
            "b": DiffPair(current=Config("b", 2), desired=Config("b", 20))
        }
        assert result.identical == {
            "a": DiffPair(current=Config("a", 1), desired=Config("a", 1))
        }

    def test_diff_iterables_duplicate_keys_uses_last(self) -> None:
        """Test diff_iterables with duplicate keys (dict construction uses last value)."""
        current = [
            {"name": "a", "value": 1},
            {"name": "a", "value": 2},  # Duplicate key, this overwrites
        ]
        desired = [{"name": "a", "value": 2}]

        result = diff_iterables(current, desired, key=operator.itemgetter("name"))

        # Last item with key "a" in current is {"name": "a", "value": 2}
        assert result.add == {}
        assert result.delete == {}
        assert result.change == {}
        assert result.identical == {
            "a": DiffPair(
                current={"name": "a", "value": 2}, desired={"name": "a", "value": 2}
            )
        }
