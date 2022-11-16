from typing import Any, Mapping, MutableMapping, Optional
from reconcile.cna.assets.asset import (
    Asset,
    AssetStatus,
    AssetType,
    AssetTypeMetadata,
    AssetTypeVariable,
    AssetTypeVariableType,
    AssetError,
    asset_type_metadata_from_asset_dataclass,
    asset_type_from_raw_asset,
)
from reconcile.cna.assets.aws_assume_role import AWSAssumeRoleAsset
from reconcile.cna.assets.null import NullAsset

from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNAAssumeRoleAssetV1,
    CNAssetV1,
    NamespaceV1,
    NamespaceCNAssetV1,
)
from reconcile.utils.external_resource_spec import (
    TypedExternalResourceSpec,
)
from reconcile.utils.external_resources import PROVIDER_CNA_EXPERIMENTAL

import pytest


@pytest.fixture
def aws_assumerole_asset_type_metadata() -> AssetTypeMetadata:
    return AssetTypeMetadata(
        id=AssetType.EXAMPLE_AWS_ASSUMEROLE,
        bindable=True,
        variables={
            AssetTypeVariable(
                name="role_arn",
                type=AssetTypeVariableType.STRING,
            ),
            AssetTypeVariable(
                name="verify-slug",
                type=AssetTypeVariableType.STRING,
                default="verify-slug",
            ),
        },
    )


def raw_asset(
    id: str,
    name: str,
    asset_type: AssetType,
    status: AssetStatus,
    parameters: dict[str, str],
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": "CNA",
        "href": f"/api/cna-management/v1/cnas/{id}",
        "asset_type": asset_type.value,
        "name": name,
        "status": status.value,
        "parameters": parameters,
        "creator": {
            "name": "App SRE OCM bot",
            "email": "sd-app-sre+ocm@redhat.com",
            "username": "sd-app-sre-ocm-bot",
        },
        "created_at": "2022-10-27T12:08:27.98559Z",
        "updated_at": "2022-10-27T12:08:27.98559Z",
    }


@pytest.fixture
def raw_aws_assumerole_asset() -> dict[str, Any]:
    return raw_asset(
        "123",
        "test",
        AssetType.EXAMPLE_AWS_ASSUMEROLE,
        AssetStatus.READY,
        {"role_arn": "1234", "verify-slug": "verify-slug"},
    )


@pytest.fixture
def aws_assumerole_asset(
    raw_aws_assumerole_asset: MutableMapping[str, Any],
) -> AWSAssumeRoleAsset:
    asset = Asset.from_api_mapping(
        raw_aws_assumerole_asset,
        AWSAssumeRoleAsset,
    )
    assert isinstance(asset, AWSAssumeRoleAsset)
    return asset


def test_asset_type_extraction_from_raw(raw_aws_assumerole_asset: Mapping[str, Any]):
    assert AssetType.EXAMPLE_AWS_ASSUMEROLE == asset_type_from_raw_asset(
        raw_aws_assumerole_asset
    )


def test_from_api_mapping(
    raw_aws_assumerole_asset: MutableMapping[str, Any],
):
    asset = Asset.from_api_mapping(raw_aws_assumerole_asset, AWSAssumeRoleAsset)
    assert isinstance(asset, AWSAssumeRoleAsset)
    assert asset.id == raw_aws_assumerole_asset["id"]
    assert asset.href == raw_aws_assumerole_asset["href"]
    assert asset.name == raw_aws_assumerole_asset["name"]
    assert asset.status == AssetStatus(raw_aws_assumerole_asset["status"])
    assert asset.role_arn == raw_aws_assumerole_asset["parameters"]["role_arn"]
    assert asset.verify_slug == raw_aws_assumerole_asset["parameters"]["verify-slug"]


def test_from_api_mapping_required_parameter_missing(
    raw_aws_assumerole_asset: MutableMapping[str, Any],
):
    raw_aws_assumerole_asset["parameters"].pop("role_arn")
    with pytest.raises(AssetError) as e:
        Asset.from_api_mapping(
            raw_aws_assumerole_asset,
            AWSAssumeRoleAsset,
        )
    assert str(e.value).startswith("Inconsistent asset")


def test_api_payload(aws_assumerole_asset: AWSAssumeRoleAsset):
    assert aws_assumerole_asset.api_payload() == {
        "asset_type": aws_assumerole_asset.asset_type().value,
        "name": aws_assumerole_asset.name,
        "parameters": {
            "role_arn": aws_assumerole_asset.role_arn,
            "verify-slug": aws_assumerole_asset.verify_slug,
        },
    }


def test_asset_type_metadata_from_asset_dataclass():
    expected = AssetTypeMetadata(
        id=AssetType.EXAMPLE_AWS_ASSUMEROLE,
        bindable=True,
        variables={
            AssetTypeVariable(
                name="role_arn",
                type=AssetTypeVariableType.STRING,
            ),
            AssetTypeVariable(
                name="verify-slug", type=AssetTypeVariableType.STRING, optional=True
            ),
        },
    )
    actual = asset_type_metadata_from_asset_dataclass(AWSAssumeRoleAsset)
    assert expected == actual


def test_update_from():
    id = "1234"
    name = "name"
    href = "href"
    status = AssetStatus.READY

    desired_asset = AWSAssumeRoleAsset(
        id=None,
        href=None,
        status=None,
        name=name,
        bindings=set(),
        role_arn="new_arn",
        verify_slug="new_verify_slug",
    )

    current_asset = AWSAssumeRoleAsset(
        id=id,
        href=href,
        name=name,
        status=status,
        bindings=set(),
        role_arn="old_arn",
        verify_slug="old_verify_slug",
    )

    update_asset = current_asset.update_from(desired_asset)
    assert isinstance(update_asset, AWSAssumeRoleAsset)
    assert update_asset.id == id
    assert update_asset.href == href
    assert update_asset.name == name
    assert update_asset.status == status
    assert update_asset.role_arn == "new_arn"
    assert update_asset.verify_slug == "new_verify_slug"


def test_asset_comparion_ignorable_fields():
    name = "name"
    arn = "arn"
    verify_slug = "verify-slug"
    asset_1 = AWSAssumeRoleAsset(
        id="id",
        href="href",
        status=AssetStatus.READY,
        bindings=set(),
        name=name,
        role_arn=arn,
        verify_slug=verify_slug,
    )

    asset_2 = AWSAssumeRoleAsset(
        id=None,
        href=None,
        status=AssetStatus.TERMINATED,
        bindings=set(),
        name=name,
        role_arn=arn,
        verify_slug=verify_slug,
    )

    assert asset_1.asset_properties() == asset_2.asset_properties()


def test_asset_properties_extraction():
    AWSAssumeRoleAsset(
        id=None,
        href=None,
        status=AssetStatus.TERMINATED,
        bindings=set(),
        name="name",
        role_arn="arn",
        verify_slug="slug",
    ).asset_properties() == {
        "role_arn": "arn",
        "verify_slug": "slug",
    }


def build_assume_role_typed_external_resource(
    identifier: str,
    role_arn: str,
    verify_slug_override: Optional[str],
    verify_slug_default: Optional[str],
) -> TypedExternalResourceSpec[CNAssetV1]:
    resource = {
        "provider": AWSAssumeRoleAsset.provider(),
        "identifier": identifier,
        "aws_account": {
            "name": "acc",
            "cna": {"defaultRoleARN": role_arn, "moduleRoleARNS": None},
        },
        "overrides": {
            "slug": verify_slug_override,
        },
        "defaults": {
            "slug": verify_slug_default,
        },
    }
    namespace_resource = {
        "provider": PROVIDER_CNA_EXPERIMENTAL,
        "provisioner": {"name": "some-ocm-org"},
        "resources": [resource],
    }
    namespace = {
        "name": "ns-name",
        "managedExternalResources": True,
        "cluster": {
            "spec": None,
        },
        "externalResources": [namespace_resource],
    }
    return TypedExternalResourceSpec[CNAssetV1](
        namespace_spec=NamespaceV1(**namespace),
        namespace_external_resource=NamespaceCNAssetV1(**namespace_resource),
        spec=CNAAssumeRoleAssetV1(**resource),
    )


def test_from_external_resources_with_default():
    identifier = "my_id"
    role_arn = "arn"
    verify_slug_default = "slug-default"
    spec = build_assume_role_typed_external_resource(
        identifier, role_arn, None, verify_slug_default
    )
    asset = AWSAssumeRoleAsset.from_external_resources(spec)

    assert isinstance(asset, AWSAssumeRoleAsset)
    assert asset.name == identifier
    assert asset.role_arn == role_arn
    assert asset.verify_slug == verify_slug_default


def test_from_external_resources_with_no_override_and_no_default():
    identifier = "my_id"
    role_arn = "arn"
    spec = build_assume_role_typed_external_resource(identifier, role_arn, None, None)
    asset = AWSAssumeRoleAsset.from_external_resources(spec)

    assert isinstance(asset, AWSAssumeRoleAsset)
    assert asset.name == identifier
    assert asset.role_arn == role_arn
    assert asset.verify_slug is None


def test_from_external_resources_with_override():
    identifier = "my_id"
    role_arn = "arn"
    verify_slug_override = "slug-override"
    verify_slug_default = "slug-default"
    spec = build_assume_role_typed_external_resource(
        identifier, role_arn, verify_slug_override, verify_slug_default
    )
    asset = AWSAssumeRoleAsset.from_external_resources(spec)

    assert isinstance(asset, AWSAssumeRoleAsset)
    assert asset.name == identifier
    assert asset.role_arn == role_arn
    assert asset.verify_slug == verify_slug_override


def test_from_external_resource_wrong_class():
    spec = build_assume_role_typed_external_resource("id", "arn", "slug", "def")
    with pytest.raises(AssetError):
        NullAsset.from_external_resources(spec)
