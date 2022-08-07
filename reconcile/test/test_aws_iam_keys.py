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
