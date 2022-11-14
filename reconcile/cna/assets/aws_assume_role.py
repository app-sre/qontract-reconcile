from __future__ import annotations
from pydantic.dataclasses import dataclass
from pydantic import Field
from typing import Optional

from reconcile.cna.assets.asset import (
    Asset,
    AssetError,
    AssetType,
    AssetStatus,
    AssetModelConfig,
)
from reconcile.cna.assets.aws_utils import aws_role_arn_for_module
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNAAssumeRoleAssetV1,
)


@dataclass(frozen=True, config=AssetModelConfig)
class AWSAssumeRoleAsset(Asset[CNAAssumeRoleAssetV1]):
    verify_slug: Optional[str] = Field(None, alias="verify-slug")
    role_arn: str = Field(alias="role_arn")

    @staticmethod
    def provider() -> str:
        return "aws-assume-role"

    @staticmethod
    def asset_type() -> AssetType:
        return AssetType.EXAMPLE_AWS_ASSUMEROLE

    @staticmethod
    def from_query_class(asset: CNAAssumeRoleAssetV1) -> Asset:
        aws_cna_cfg = asset.account.cna
        role_arn = aws_role_arn_for_module(
            aws_cna_cfg, AssetType.EXAMPLE_AWS_ASSUMEROLE.value
        )
        if role_arn is None:
            raise AssetError(
                f"No CNA roles configured for AWS account {asset.account.name}"
            )

        return AWSAssumeRoleAsset(
            id=None,
            href=None,
            status=AssetStatus.UNKNOWN,
            name=asset.identifier,
            verify_slug=asset.overrides.slug if asset.overrides else None,
            role_arn=role_arn,
        )
