import pytest
import reconcile.aws_iam_keys as integ


def test_filter_accounts_with_account_name():
    a = {"name": "a", "deleteKeys": ["AKIA"]}
    b = {"name": "b", "deleteKeys": ["AKIA"]}
    accounts = [a, b]
    filtered = integ.filter_accounts(accounts, a["name"])
    assert filtered == [a]


def test_filter_accounts_without_account_name():
    a = {"name": "a", "deleteKeys": ["AKIA"]}
    b = {"name": "b", "deleteKeys": ["AKIA"]}
    accounts = [a, b]
    filtered = integ.filter_accounts(accounts, None)
    assert filtered == accounts


def test_filter_accounts_without_delete_keys():
    a = {"name": "a", "deleteKeys": ["AKIA"]}
    b = {"name": "b"}
    accounts = [a, b]
    filtered = integ.filter_accounts(accounts, None)
    assert filtered == [a]


def test_get_keys_to_delete():
    a = {"name": "a", "deleteKeys": ["k1", "k2"]}
    b = {"name": "b", "deleteKeys": None}
    c = {"name": "c", "deleteKeys": []}
    accounts = [a, b, c]
    expected_result = {a["name"]: a["deleteKeys"]}
    keys_to_delete = integ.get_keys_to_delete(accounts)
    assert keys_to_delete == expected_result


class StateMock:
    def __init__(self):
        self.data = {}

    def get(self, key, *args):
        return self.data.get(key, args[0])

    def add(self, key, value, force):
        self.data[key] = value


@pytest.fixture
def state():
    return StateMock()


def test_should_run_true(state):
    keys_to_delete = {"a": ["k1"]}
    assert integ.should_run(state, keys_to_delete) is True


def test_should_run_false(state):
    keys_to_delete = {"a": ["k1"]}
    state.data.update(keys_to_delete)
    assert integ.should_run(state, keys_to_delete) is False


def test_update_state(state):
    keys_to_update = {"a": ["k1"]}
    integ.update_state(state, keys_to_update)
    assert state.data == keys_to_update
