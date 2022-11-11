from typing import Any, Mapping, MutableMapping
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
        role_arn="new_arn",
        verify_slug="new_verify_slug",
    )

    current_asset = AWSAssumeRoleAsset(
        id=id,
        href=href,
        name=name,
        status=status,
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
        name=name,
        role_arn=arn,
        verify_slug=verify_slug,
    )

    asset_2 = AWSAssumeRoleAsset(
        id=None,
        href=None,
        status=AssetStatus.TERMINATED,
        name=name,
        role_arn=arn,
        verify_slug=verify_slug,
    )

    assert asset_1.asset_properties() == asset_2.asset_properties()


def test_asset_properties_extration():
    AWSAssumeRoleAsset(
        id=None,
        href=None,
        status=AssetStatus.TERMINATED,
        name="name",
        role_arn="arn",
        verify_slug="slug",
    ).asset_properties() == {
        "role_arn": "arn",
        "verify_slug": "slug",
    }
