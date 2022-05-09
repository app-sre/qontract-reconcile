from typing import Any
from pydantic import ValidationError
import pytest
from reconcile.utils.openshift_resource import (
    SECRET_MAX_KEY_LENGTH,
    base64_encode_secret_field_value,
)
from reconcile.utils.terraform_resource_spec import (
    TerraformResourceUniqueKey,
    TerraformResourceSpec,
)


def test_identifier_creation_from_dict():
    id = TerraformResourceUniqueKey.from_dict(
        {"identifier": "i", "provider": "p", "account": "a"}
    )
    assert id.identifier == "i"
    assert id.provider == "p"
    assert id.account == "a"


def test_identifier_missing():
    with pytest.raises(ValidationError):
        TerraformResourceUniqueKey.from_dict(
            {"identifier": None, "provider": "p", "account": "a"}
        )
    with pytest.raises(KeyError):
        TerraformResourceUniqueKey.from_dict({"provider": "p", "account": "a"})


def test_identifier_account_missing():
    with pytest.raises(ValidationError):
        TerraformResourceUniqueKey.from_dict(
            {"identifier": "i", "account": None, "provider": "p"}
        )
    with pytest.raises(KeyError):
        TerraformResourceUniqueKey.from_dict({"identifier": "i", "provider": "p"})


def test_identifier_provider_missing():
    with pytest.raises(ValidationError):
        TerraformResourceUniqueKey.from_dict(
            {"identifier": "i", "account": "a", "provider": None}
        )
    with pytest.raises(KeyError):
        TerraformResourceUniqueKey.from_dict({"identifier": "i", "account": "a"})


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
    assert s._annotations() == {"key": "value"}


def test_spec_annotation_parsing_none_present():
    s = TerraformResourceSpec(
        resource={
            "identifier": "i",
            "provider": "p",
            "account": "a",
        },
        namespace={},
    )
    assert s._annotations() == {}


@pytest.fixture
def resource_secret() -> dict[str, Any]:
    return {"yakk_name": "Furry", "visual_characteristics": "furry", "mood": "grumpy"}


@pytest.fixture
def spec() -> TerraformResourceSpec:
    return TerraformResourceSpec(
        resource={
            "identifier": "i",
            "provider": "p",
            "account": "a",
        },
        namespace={},
    )


#
# tests for terraform output format
#


def test_terraform_output_with_when_no_secret(spec: TerraformResourceSpec):
    output_secret = spec.build_oc_secret("int", "1.0")
    assert output_secret.body["data"] == {}


def test_terraform_generic_secret_output_format(
    spec: TerraformResourceSpec, resource_secret: dict[str, Any]
):
    spec.resource["output_format"] = {  # type: ignore[index]
        "provider": "generic-secret",
        "data": """
            motd: The {{ mood }} Yakk {{ yakk_name }} is {{ visual_characteristics }}.
        """,
    }
    spec.secret = resource_secret

    output_secret = spec.build_oc_secret("int", "1.0")
    assert output_secret.body["data"]["motd"] == base64_encode_secret_field_value(
        "The grumpy Yakk Furry is furry."
    )


def test_terraform_generic_secret_output_format_no_data(
    spec: TerraformResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows backwards compatibility with the simple dict output when
    no data is given but the provider is specified
    """
    spec.resource["output_format"] = {  # type: ignore[index]
        "provider": "generic-secret",
    }
    spec.secret = resource_secret

    output_secret = spec.build_oc_secret("int", "1.0")
    assert len(output_secret.body["data"]) == len(resource_secret)
    for k, v in resource_secret.items():
        assert output_secret.body["data"][k] == base64_encode_secret_field_value(v)


def test_terraform_no_output_format_provider(
    spec: TerraformResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows full backwards compatibility when no provider has been specified
    """
    spec.secret = resource_secret

    output_secret = spec.build_oc_secret("int", "1.0")
    assert len(output_secret.body["data"]) == len(resource_secret)
    for k, v in resource_secret.items():
        assert output_secret.body["data"][k] == base64_encode_secret_field_value(v)


def test_terraform_unknown_output_format_provider(spec: TerraformResourceSpec):
    """
    this test expects the secret generation to fail when an unknown provider is
    given. while the schema usually protects against such cases, additional protection
    in code is a good thing.
    """
    spec.resource["output_format"] = {  # type: ignore[index]
        "provider": "unknown-provider"
    }
    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_format_not_a_dict(
    spec: TerraformResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows how a data template for a generic-secret provider must result
    in a valid dict and fails otherwise
    """
    spec.resource["output_format"] = {  # type: ignore[index]
        "provider": "generic-secret",
        "data": "not_a_dict",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_format_not_str_keys(
    spec: TerraformResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows how a data template for a generic-secret provider must produce
    string keys
    """
    spec.resource["output_format"] = {  # type: ignore[index]
        "provider": "generic-secret",
        "data": "1: value",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_format_not_str_val(
    spec: TerraformResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows how a data template for a generic-secret provider must produce
    string values
    """
    spec.resource["output_format"] = {  # type: ignore[index]
        "provider": "generic-secret",
        "data": "key: 1",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_key_too_long(
    spec: TerraformResourceSpec, resource_secret: dict[str, Any]
):
    """
    tests for too long secret keys (max length in kubernetes is 253 characters )
    """
    long_key = "a" * (SECRET_MAX_KEY_LENGTH + 1)
    spec.resource["output_format"] = {  # type: ignore[index]
        "provider": "generic-secret",
        "data": f"{ long_key }: value",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")
