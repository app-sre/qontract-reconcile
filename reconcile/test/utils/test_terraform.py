from reconcile.utils.terraform import safe_resource_id


def test_sanitize_resource_with_dots():
    assert safe_resource_id("foo.example.com") == "foo_example_com"


def test_sanitize_resource_with_wildcard():
    assert safe_resource_id("*.foo.example.com") == "_star_foo_example_com"


def test_sanitize_resource_begins_with_number():
    assert safe_resource_id("0xyz") == "_0xyz"
