from collections.abc import Mapping
from typing import Any

import pytest

import reconcile.aws_iam_keys as integ
from reconcile.utils.state import State


def test_filter_accounts_with_account_name() -> None:
    a: dict[str, Any] = {"name": "a", "deleteKeys": ["AKIA"]}
    b: dict[str, Any] = {"name": "b", "deleteKeys": ["AKIA"]}
    accounts = [a, b]
    filtered = integ.filter_accounts(accounts, a["name"])
    assert filtered == [a]


def test_filter_accounts_without_account_name() -> None:
    a: dict[str, Any] = {"name": "a", "deleteKeys": ["AKIA"]}
    b: dict[str, Any] = {"name": "b", "deleteKeys": ["AKIA"]}
    accounts = [a, b]
    filtered = integ.filter_accounts(accounts, None)
    assert filtered == accounts


def test_filter_accounts_without_delete_keys() -> None:
    a: dict[str, Any] = {"name": "a", "deleteKeys": ["AKIA"]}
    b: dict[str, Any] = {"name": "b"}
    accounts = [a, b]
    filtered = integ.filter_accounts(accounts, None)
    assert filtered == [a]


def test_get_keys_to_delete() -> None:
    a: dict[str, Any] = {"name": "a", "deleteKeys": ["k1", "k2"]}
    b: dict[str, Any] = {"name": "b", "deleteKeys": None}
    c: dict[str, Any] = {"name": "c", "deleteKeys": []}
    accounts = [a, b, c]
    expected_result = {a["name"]: a["deleteKeys"]}
    keys_to_delete = integ.get_keys_to_delete(accounts)
    assert keys_to_delete == expected_result


class StateMock(State):
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str, *args: Any) -> Any:
        return self.data.get(key, args[0])

    def add(
        self,
        key: str,
        value: Any = None,
        metadata: Mapping[str, str] | None = None,
        force: bool = False,
    ) -> None:
        self.data[key] = value


@pytest.fixture
def state() -> StateMock:
    return StateMock()


def test_should_run_true(state: StateMock) -> None:
    keys_to_delete = {"a": ["k1"]}
    assert integ.should_run(state, keys_to_delete) is True


def test_should_run_false(state: StateMock) -> None:
    keys_to_delete = {"a": ["k1"]}
    state.data.update(keys_to_delete)
    assert integ.should_run(state, keys_to_delete) is False


def test_update_state(state: StateMock) -> None:
    keys_to_update = {"a": ["k1"]}
    integ.update_state(state, keys_to_update)
    assert state.data == keys_to_update


def test_filter_accounts_with_disable_keys() -> None:
    a: dict[str, Any] = {"name": "a", "disableKeys": ["AKIA"]}
    b: dict[str, Any] = {"name": "b", "deleteKeys": ["AKIA"]}
    c: dict[str, Any] = {"name": "c"}
    accounts = [a, b, c]
    filtered = integ.filter_accounts(accounts, None)
    assert filtered == [a, b]


def test_filter_accounts_with_both_disable_and_delete_keys() -> None:
    a: dict[str, Any] = {"name": "a", "disableKeys": ["AKIA1"], "deleteKeys": ["AKIA2"]}
    b: dict[str, Any] = {"name": "b"}
    accounts = [a, b]
    filtered = integ.filter_accounts(accounts, None)
    assert filtered == [a]


def test_get_keys_to_disable() -> None:
    a: dict[str, Any] = {"name": "a", "disableKeys": ["k1", "k2"]}
    b: dict[str, Any] = {"name": "b", "disableKeys": None}
    c: dict[str, Any] = {"name": "c", "disableKeys": []}
    d: dict[str, Any] = {"name": "d"}
    accounts = [a, b, c, d]
    expected_result = {a["name"]: a["disableKeys"]}
    keys_to_disable = integ.get_keys_to_disable(accounts)
    assert keys_to_disable == expected_result


def test_should_run_with_disable_keys_true(state: StateMock) -> None:
    keys_to_delete = {"a": ["k1"]}
    keys_to_disable = {"b": ["k2"]}
    assert integ.should_run(state, keys_to_delete, keys_to_disable) is True


def test_should_run_with_disable_keys_false(state: StateMock) -> None:
    keys_to_delete = {"a": ["k1"]}
    keys_to_disable = {"b": ["k2"]}
    state.data.update(keys_to_delete)
    state.data["b_disable"] = keys_to_disable["b"]
    assert integ.should_run(state, keys_to_delete, keys_to_disable) is False


def test_should_run_with_disable_keys_changed(state: StateMock) -> None:
    keys_to_delete = {"a": ["k1"]}
    keys_to_disable = {"b": ["k2"]}
    state.data.update(keys_to_delete)
    state.data["b_disable"] = ["k3"]  # Different key
    assert integ.should_run(state, keys_to_delete, keys_to_disable) is True


def test_update_state_with_disable_keys(state: StateMock) -> None:
    keys_to_update = {"a": ["k1"]}
    keys_to_disable = {"b": ["k2"]}
    integ.update_state(state, keys_to_update, keys_to_disable)
    expected_data = {"a": ["k1"], "b_disable": ["k2"]}
    assert state.data == expected_data
