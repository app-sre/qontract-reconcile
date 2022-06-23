from typing import Any
from pydantic import ValidationError
import pytest
from reconcile.utils.openshift_resource import (
    SECRET_MAX_KEY_LENGTH,
    base64_encode_secret_field_value,
)
from reconcile.utils.external_resource_spec import (
    ExternalResourceUniqueKey,
    ExternalResourceSpec,
)


def test_identifier_creation_from_spec():
    id = ExternalResourceUniqueKey.from_spec(
        ExternalResourceSpec(
            provision_provider="p",
            provisioner={"name": "a"},
            resource={
                "identifier": "i",
                "provider": "p",
            },
            namespace={},
        )
    )
    assert id.identifier == "i"
    assert id.provider == "p"
    assert id.provisioner_name == "a"


def test_identifier_missing():
    with pytest.raises(ValidationError):
        ExternalResourceUniqueKey.from_spec(
            ExternalResourceSpec(
                provision_provider="p",
                provisioner={"name": "a"},
                resource={
                    "identifier": None,
                    "provider": "p",
                },
                namespace={},
            )
        )
    with pytest.raises(KeyError):
        ExternalResourceUniqueKey.from_spec(
            ExternalResourceSpec(
                provision_provider="p",
                provisioner={"name": "a"},
                resource={
                    "provider": "p",
                },
                namespace={},
            )
        )


def test_identifier_account_missing():
    with pytest.raises(ValidationError):
        ExternalResourceUniqueKey.from_spec(
            ExternalResourceSpec(
                provision_provider="p",
                provisioner={"name": None},
                resource={
                    "identifier": "i",
                    "provider": "p",
                },
                namespace={},
            )
        )
    with pytest.raises(KeyError):
        ExternalResourceUniqueKey.from_spec(
            ExternalResourceSpec(
                provision_provider="p",
                provisioner={},
                resource={
                    "identifier": "i",
                    "provider": "p",
                },
                namespace={},
            )
        )


def test_identifier_provider_missing():
    with pytest.raises(ValidationError):
        ExternalResourceUniqueKey.from_spec(
            ExternalResourceSpec(
                provision_provider="p",
                provisioner={"name": "a"},
                resource={
                    "identifier": "i",
                    "provider": None,
                },
                namespace={},
            )
        )
    with pytest.raises(KeyError):
        ExternalResourceUniqueKey.from_spec(
            ExternalResourceSpec(
                provision_provider="p",
                provisioner={"name": "a"},
                resource={
                    "identifier": "i",
                },
                namespace={},
            )
        )


def test_spec_output_prefix():
    s = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "a"},
        resource={"identifier": "i", "provider": "p"},
        namespace={},
    )
    assert s.output_prefix == "i-p"


def test_spec_implicit_output_resource_name():
    s = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "a"},
        resource={"identifier": "i", "provider": "p"},
        namespace={},
    )
    assert s.output_resource_name == "i-p"


def test_spec_explicit_output_resource_name():
    s = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "a"},
        resource={
            "identifier": "i",
            "provider": "p",
            "output_resource_name": "explicit",
        },
        namespace={},
    )
    assert s.output_resource_name == "explicit"


def test_spec_annotation_parsing():
    s = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "a"},
        resource={
            "identifier": "i",
            "provider": "p",
            "annotations": '{"key": "value"}',
        },
        namespace={},
    )
    assert s.annotations() == {"key": "value"}


def test_spec_annotation_parsing_none_present():
    s = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "a"},
        resource={
            "identifier": "i",
            "provider": "p",
        },
        namespace={},
    )
    assert s.annotations() == {}


def test_spec_tags():
    s = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "a"},
        resource={
            "identifier": "i",
            "provider": "p",
        },
        namespace={
            "name": "ns",
            "cluster": {
                "name": "c",
            },
            "environment": {
                "name": "env",
            },
            "app": {
                "name": "app",
            },
        },
    )
    expected = {
        "managed_by_integration": "int",
        "cluster": "c",
        "namespace": "ns",
        "environment": "env",
        "app": "app",
    }
    assert s.tags("int") == expected


@pytest.fixture
def resource_secret() -> dict[str, Any]:
    return {"yakk_name": "Furry", "visual_characteristics": "furry", "mood": "grumpy"}


@pytest.fixture
def spec() -> ExternalResourceSpec:
    return ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "a"},
        resource={
            "identifier": "i",
            "provider": "p",
        },
        namespace={},
    )


#
# tests for terraform output format
#


def test_terraform_output_with_when_no_secret(spec: ExternalResourceSpec):
    output_secret = spec.build_oc_secret("int", "1.0")
    assert output_secret.body["data"] == {}


def test_terraform_generic_secret_output_format(
    spec: ExternalResourceSpec, resource_secret: dict[str, Any]
):
    spec.resource["output_format"] = {
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
    spec: ExternalResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows backwards compatibility with the simple dict output when
    no data is given but the provider is specified
    """
    spec.resource["output_format"] = {
        "provider": "generic-secret",
    }
    spec.secret = resource_secret

    output_secret = spec.build_oc_secret("int", "1.0")
    assert len(output_secret.body["data"]) == len(resource_secret)
    for k, v in resource_secret.items():
        assert output_secret.body["data"][k] == base64_encode_secret_field_value(v)


def test_terraform_no_output_format_provider(
    spec: ExternalResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows full backwards compatibility when no provider has been specified
    """
    spec.secret = resource_secret

    output_secret = spec.build_oc_secret("int", "1.0")
    assert len(output_secret.body["data"]) == len(resource_secret)
    for k, v in resource_secret.items():
        assert output_secret.body["data"][k] == base64_encode_secret_field_value(v)


def test_terraform_unknown_output_format_provider(spec: ExternalResourceSpec):
    """
    this test expects the secret generation to fail when an unknown provider is
    given. while the schema usually protects against such cases, additional protection
    in code is a good thing.
    """
    spec.resource["output_format"] = {"provider": "unknown-provider"}
    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_format_not_a_dict(
    spec: ExternalResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows how a data template for a generic-secret provider must result
    in a valid dict and fails otherwise
    """
    spec.resource["output_format"] = {
        "provider": "generic-secret",
        "data": "not_a_dict",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_format_not_str_keys(
    spec: ExternalResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows how a data template for a generic-secret provider must produce
    string keys
    """
    spec.resource["output_format"] = {
        "provider": "generic-secret",
        "data": "1: value",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_format_not_str_val(
    spec: ExternalResourceSpec, resource_secret: dict[str, Any]
):
    """
    this test shows how a data template for a generic-secret provider must produce
    string values
    """
    spec.resource["output_format"] = {
        "provider": "generic-secret",
        "data": "key: 1",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")


def test_terraform_generic_secret_output_key_too_long(
    spec: ExternalResourceSpec, resource_secret: dict[str, Any]
):
    """
    tests for too long secret keys (max length in kubernetes is 253 characters )
    """
    long_key = "a" * (SECRET_MAX_KEY_LENGTH + 1)
    spec.resource["output_format"] = {
        "provider": "generic-secret",
        "data": f"{ long_key }: value",
    }
    spec.secret = resource_secret

    with pytest.raises(ValueError):
        spec.build_oc_secret("int", "1.0")
