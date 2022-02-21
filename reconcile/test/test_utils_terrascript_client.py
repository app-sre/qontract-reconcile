import reconcile.utils.terrascript_client as tsclient


def test_sanitize_resource_with_dots():
    assert tsclient.safe_resource_id("foo.example.com") == "foo_example_com"


def test_sanitize_resource_with_wildcard():
    assert tsclient.safe_resource_id("*.foo.example.com") == \
        "_star_foo_example_com"


def test_aws_username_org():
    ts = tsclient.TerrascriptClient('', '', 1, [])
    result = 'org'
    user = {
        'org_username': result
    }
    assert ts._get_aws_username(user) == result


def test_aws_username_aws():
    ts = tsclient.TerrascriptClient('', '', 1, [])
    result = 'aws'
    user = {
        'org_username': 'org',
        'aws_username': result
    }
    assert ts._get_aws_username(user) == result


def test_validate_mandatory_policies():
    mandatory_policy = {
        'name': 'mandatory',
        'mandatory': True,
    }
    not_mandatory_policy = {
        'name': 'not-mandatory',
    }
    account = {
        'name': 'acc',
        'policies': [mandatory_policy, not_mandatory_policy]
    }
    ts = tsclient.TerrascriptClient('', '', 1, [])
    assert ts._validate_mandatory_policies(
        account, [mandatory_policy], 'role') is True
    assert ts._validate_mandatory_policies(
        account, [not_mandatory_policy], 'role') is False
