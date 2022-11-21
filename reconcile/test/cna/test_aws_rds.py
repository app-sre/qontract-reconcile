import json
from reconcile.cna.assets.asset import AssetError
from reconcile.cna.assets.aws_rds import AWSRDSAsset
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNARDSInstanceV1,
    CNARDSInstanceDefaultsV1,
    AWSVPCV1,
)
from reconcile.gql_definitions.cna.queries.aws_arn import (
    CNAAWSAccountRoleARNs,
    CNAAWSSpecV1,
)

import pytest

asset_identifier = "identifier"
db_name = "instance-name"
vpc_id = "vpc-id"
region = "region"
arn = "arn"
engine = "engine"
engine_version = "14.2"
allocated_storage = 10
max_allocated_storage = 20
instance_class = "instance-class"
db_subnet_group_name = "db-subnet-group-name"
backup_retention_period = 7
backup_window = "backup-window"
maintenance_window = "maintenance_window"
username = "username"
apply_immediately = True
multi_az = True
deletion_protection = True


@pytest.fixture
def rds_query_asset() -> CNARDSInstanceV1:
    return CNARDSInstanceV1(
        provider=AWSRDSAsset.provider(),
        identifier=asset_identifier,
        name=db_name,
        overrides=None,
        defaults=CNARDSInstanceDefaultsV1(
            vpc=AWSVPCV1(
                vpc_id=vpc_id,
                region=region,
                account=CNAAWSAccountRoleARNs(
                    name="acc",
                    cna=CNAAWSSpecV1(defaultRoleARN=arn, moduleRoleARNS=None),
                ),
            ),
            engine=engine,
            engine_version=engine_version,
            allocated_storage=allocated_storage,
            max_allocated_storage=max_allocated_storage,
            instance_class=instance_class,
            db_subnet_group_name=db_subnet_group_name,
            username=username,
            maintenance_window=maintenance_window,
            backup_retention_period=backup_retention_period,
            backup_window=backup_window,
            multi_az=multi_az,
            deletion_protection=deletion_protection,
            apply_immediately=apply_immediately,
        ),
    )


def test_from_query_class(rds_query_asset: CNARDSInstanceV1):
    asset = AWSRDSAsset.from_query_class(rds_query_asset)
    assert isinstance(asset, AWSRDSAsset)
    assert asset.name == asset_identifier
    assert asset.region == region
    assert asset.identifier == db_name
    assert asset.db_subnet_group_name == db_subnet_group_name
    assert asset.instance_class == instance_class
    assert asset.engine == engine
    assert asset.engine_version == engine_version
    assert asset.major_engine_version == "14"
    assert asset.allocated_storage == str(allocated_storage)
    assert asset.max_allocated_storage == str(max_allocated_storage)
    assert asset.role_arn == arn
    assert asset.backup_retention_period == backup_retention_period
    assert asset.apply_immediately == apply_immediately
    assert asset.multi_az == multi_az
    assert asset.deletion_protection == deletion_protection


def test_from_query_class_db_name_default(rds_query_asset: CNARDSInstanceV1):
    rds_query_asset.name = None
    asset = AWSRDSAsset.from_query_class(rds_query_asset)
    assert isinstance(asset, AWSRDSAsset)
    assert asset.identifier == asset_identifier


def test_from_query_class_engine_version_override(rds_query_asset: CNARDSInstanceV1):
    engine_version_override = "15.2"
    rds_query_asset.name = None
    rds_query_asset.overrides = {
        "engine_version": engine_version_override
    }  # type: ignore
    asset = AWSRDSAsset.from_query_class(rds_query_asset)
    assert isinstance(asset, AWSRDSAsset)
    assert asset.engine_version == engine_version_override
