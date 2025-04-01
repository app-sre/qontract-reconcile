from typing import Any, cast

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


class StateMock:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str, *args: Any) -> Any:
        return self.data.get(key, args[0])

    def add(self, key: str, value: Any, force: bool) -> None:
        self.data[key] = value


@pytest.fixture
def state_mock() -> StateMock:
    return StateMock()


def test_should_run_true(state_mock: StateMock) -> None:
    keys_to_delete = {"a": ["k1"]}
    state = cast(State, state_mock)
    assert integ.should_run(state, keys_to_delete) is True


def test_should_run_false(state_mock: StateMock) -> None:
    keys_to_delete = {"a": ["k1"]}
    state_mock.data.update(keys_to_delete)
    state = cast(State, state_mock)
    assert integ.should_run(state, keys_to_delete) is False


def test_update_state(state_mock: StateMock) -> None:
    keys_to_update = {"a": ["k1"]}
    state = cast(State, state_mock)
    integ.update_state(state, keys_to_update)
    assert state_mock.data == keys_to_update
