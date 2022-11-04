from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

from reconcile.cna.assets.asset import Asset, AssetError, AssetStatus, AssetType
from reconcile.gql_definitions.cna.queries.cna_resources import CNAAssumeRoleAssetV1


@dataclass(frozen=True)
class AWSAssumeRoleAsset(Asset):
    slug: str
    role_arn: str

    def api_payload(self) -> dict[str, Any]:
        return {
            "asset_type": AssetType.EXAMPLE_AWS_ASSUMEROLE,
            "name": self.name,
            "parameters": {
                "slug": self.slug,
                "role_arn": self.role_arn,
            },
        }

    def update_from(self, asset: Asset) -> Asset:
        if not isinstance(asset, AWSAssumeRoleAsset):
            raise AssetError(f"Cannot create AWSAssumeRoleAsset from {asset}")
        return AWSAssumeRoleAsset(
            uuid=self.uuid,
            href=self.href,
            status=self.status,
            name=self.name,
            kind=self.kind,
            slug=asset.slug,
            role_arn=asset.role_arn,
        )

    @staticmethod
    def from_query_class(asset: CNAAssumeRoleAssetV1) -> AWSAssumeRoleAsset:
        role_arn = asset.aws_assume_role.account.cna.default_role_arn
        for module_config in asset.aws_assume_role.account.cna.module_role_arns:
            if module_config.module == AssetType.EXAMPLE_AWS_ASSUMEROLE:
                role_arn = module_config.role_arn
                break

        return AWSAssumeRoleAsset(
            uuid=None,
            href=None,
            status=None,
            kind=AssetType.EXAMPLE_AWS_ASSUMEROLE,
            name=asset.name,
            slug=asset.aws_assume_role.slug,
            role_arn=role_arn,
        )

    @staticmethod
    def from_api_mapping(asset: Mapping[str, Any]) -> AWSAssumeRoleAsset:
        return AWSAssumeRoleAsset(
            uuid=asset.get("id"),
            href=asset.get("href"),
            status=AssetStatus(asset.get("status")),
            kind=AssetType.NULL,
            name=asset.get("name", ""),
            slug=asset.get("slug"),
            role_arn=asset.get("role_arn"),
        )
