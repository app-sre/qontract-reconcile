from __future__ import annotations
from typing import Optional
from pydantic.dataclasses import dataclass
from pydantic import Field

from reconcile.cna.assets.asset import (
    Asset,
    AssetError,
    AssetType,
    AssetModelConfig,
    AssetStatus,
)
from reconcile.cna.assets.aws_utils import aws_role_arn_for_module
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNARDSInstanceV1,
    CNAssetV1,
)


@dataclass(frozen=True, config=AssetModelConfig)
class AWSRDSAsset(Asset):
    identifier: str = Field(alias="identifier")
    vpc_id: str = Field(alias="vpc_id")
    role_arn: str = Field(alias="role_arn")
    db_subnet_group_name: str = Field(alias="db_subnet_group_name")
    instance_class: str = Field(alias="instance_class")
    allocated_storage: str = Field(alias="allocated_storage")
    max_allocated_storage: str = Field(alias="max_allocated_storage")
    engine: Optional[str] = Field(None, alias="engine")
    engine_version: Optional[str] = Field(None, alias="engine_version")
    region: Optional[str] = Field(None, alias="region")
    backup_retention_period: Optional[int] = Field(
        None, alias="backup_retention_period"
    )
    backup_window: Optional[str] = Field(None, alias="backup_window")
    maintenance_window: Optional[str] = Field(None, alias="maintenance_window")

    @staticmethod
    def provider() -> str:
        return "aws-rds"

    @staticmethod
    def asset_type() -> AssetType:
        return AssetType.AWS_RDS

    @staticmethod
    def from_query_class(asset: CNAssetV1) -> Asset:
        assert isinstance(asset, CNARDSInstanceV1)
        aws_cna_cfg = asset.aws_rds.vpc.account.cna
        role_arn = aws_role_arn_for_module(aws_cna_cfg, AssetType.AWS_RDS.value)
        if role_arn is None:
            raise AssetError(
                f"No CNA roles configured for AWS account {asset.aws_rds.vpc.account.name}"
            )

        return AWSRDSAsset(
            id=None,
            href=None,
            status=AssetStatus.UNKNOWN,
            name=asset.name,
            identifier=asset.name,
            vpc_id=asset.aws_rds.vpc.vpc_id,
            role_arn=role_arn,
            db_subnet_group_name=asset.aws_rds.db_subnet_group_name,
            engine=asset.aws_rds.engine,
            engine_version=asset.aws_rds.engine_version,
            instance_class=asset.aws_rds.instance_class,
            allocated_storage=str(asset.aws_rds.allocated_storage),
            max_allocated_storage=str(asset.aws_rds.max_allocated_storage),
            region=asset.aws_rds.vpc.region,
            backup_retention_period=asset.aws_rds.backup_retention_period,
            backup_window=asset.aws_rds.backup_window,
            maintenance_window=asset.aws_rds.maintenance_window,
        )
