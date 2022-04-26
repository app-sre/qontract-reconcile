import pytest
from reconcile.utils.terraform_resource_spec import (
    TerraformResourceIdentifier as TRI,
    TerraformResourceSpec,
)


def test_identifier_creation_from_dict():
    id = TRI.from_dict({"identifier": "i", "provider": "p", "account": "a"})
    assert id.identifier == "i"
    assert id.provider == "p"
    assert id.account == "a"


def test_identifier_creation_from_output_prefix():
    id = TRI.from_output_prefix("i-p", "a")
    assert id.identifier == "i"
    assert id.provider == "p"
    assert id.account == "a"


def test_identifier_missing():
    with pytest.raises(ValueError):
        TRI.from_dict({"provider": "p", "account": "a"})


def test_identifier_account_missing():
    with pytest.raises(ValueError):
        TRI.from_dict({"identifier": "i", "provider": "p"})


def test_identifier_provider_missing():
    with pytest.raises(ValueError):
        TRI.from_dict({"identifier": "i", "account": "a"})


def test_spec_output_prefix():
    s = TerraformResourceSpec(
        resource={"identifier": "i", "provider": "p", "account": "a"}, namespace={}
    )
    assert s.output_prefix == "i-p"


def test_spec_implicit_output_resource_name():
    s = TerraformResourceSpec(
        resource={"identifier": "i", "provider": "p", "account": "a"}, namespace={}
    )
    assert s.output_resource_name == "i-p"


def test_spec_explicit_output_resource_name():
    s = TerraformResourceSpec(
        resource={
            "identifier": "i",
            "provider": "p",
            "account": "a",
            "output_resource_name": "explicit",
        },
        namespace={},
    )
    assert s.output_resource_name == "explicit"


def test_spec_annotation_parsing():
    s = TerraformResourceSpec(
        resource={
            "identifier": "i",
            "provider": "p",
            "account": "a",
            "annotations": '{"key": "value"}',
        },
        namespace={},
    )
    assert s.annotations == {"key": "value"}


def test_spec_annotation_parsing_none_present():
    s = TerraformResourceSpec(
        resource={
            "identifier": "i",
            "provider": "p",
            "account": "a",
        },
        namespace={},
    )
    assert s.annotations == {}
