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
    CNARDSInstanceConfig,
)


@dataclass(frozen=True, config=AssetModelConfig)
class AWSRDSAsset(Asset[CNARDSInstanceV1, CNARDSInstanceConfig]):
    identifier: str = Field(alias="identifier")
    vpc_id: str = Field(alias="vpc_id")
    role_arn: str = Field(alias="role_arn")
    db_subnet_group_name: str = Field(alias="db_subnet_group_name")
    instance_class: str = Field(alias="instance_class")
    allocated_storage: str = Field(alias="allocated_storage")
    max_allocated_storage: str = Field(alias="max_allocated_storage")
    engine: Optional[str] = Field(None, alias="engine")
    engine_version: Optional[str] = Field(None, alias="engine_version")
    major_engine_version: Optional[str] = Field(None, alias="major_engine_version")
    username: Optional[str] = Field(None, alias="username")
    region: Optional[str] = Field(None, alias="region")
    backup_retention_period: Optional[int] = Field(
        None, alias="backup_retention_period"
    )
    backup_window: Optional[str] = Field(None, alias="backup_window")
    maintenance_window: Optional[str] = Field(None, alias="maintenance_window")
    multi_az: Optional[bool] = Field(None, alias="multi_az")
    deletion_protection: Optional[bool] = Field(None, alias="deletion_protection")
    apply_immediately: Optional[bool] = Field(None, alias="apply_immediately")

    @staticmethod
    def provider() -> str:
        return "aws-rds"

    @staticmethod
    def asset_type() -> AssetType:
        return AssetType.AWS_RDS

    @classmethod
    def from_query_class(cls, asset: CNARDSInstanceV1) -> Asset:
        config = cls.aggregate_config(asset)
        if config.vpc is None:
            raise AssetError("Missing VPC configuration for asset")

        aws_cna_cfg = config.vpc.account.cna
        role_arn = aws_role_arn_for_module(aws_cna_cfg, AssetType.AWS_RDS.value)
        if role_arn is None:
            raise AssetError(
                f"No CNA roles configured for AWS account {config.vpc.account.name}"
            )

        if not (db_subnet_group_name := config.db_subnet_group_name):
            raise AssetError(
                f"No db_subnet_group_name provided for RDS instance {asset.identifier}"
            )
        if not (instance_class := config.instance_class):
            raise AssetError(
                f"No instance_class provided for RDS instance {asset.identifier}"
            )
        if not (engine := config.engine):
            raise AssetError(f"No engine provided for RDS instance {asset.identifier}")
        if not (max_allocated_storage := config.max_allocated_storage):
            raise AssetError(
                f"No max_allocated_storage provided for RDS instance {asset.identifier}"
            )

        return AWSRDSAsset(
            id=None,
            href=None,
            status=AssetStatus.UNKNOWN,
            bindings=set(),
            name=asset.identifier,
            identifier=asset.name or asset.identifier,
            vpc_id=config.vpc.vpc_id,
            role_arn=role_arn,
            db_subnet_group_name=db_subnet_group_name,
            engine=engine,
            engine_version=config.engine_version,
            instance_class=instance_class,
            allocated_storage=str(config.allocated_storage),
            max_allocated_storage=str(max_allocated_storage),
            region=config.vpc.region,
            backup_retention_period=config.backup_retention_period,
            backup_window=None,
            maintenance_window=None,
            apply_immediately=config.apply_immediately,
            deletion_protection=config.deletion_protection,
            multi_az=config.multi_az,
        )
