from reconcile.cna.assets.aws_rds import AWSRDSAsset
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNARDSInstanceV1,
    CNARDSInstanceOverridesV1,
    AWSVPCV1,
)
from reconcile.gql_definitions.cna.queries.aws_account_fragment import (
    CNAAWSAccountRoleARNs,
    CNAAWSSpecV1,
)


def test_from_query_class():
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
    query_asset = CNARDSInstanceV1(
        provider=AWSRDSAsset.provider(),
        identifier=asset_identifier,
        vpc=AWSVPCV1(
            vpc_id=vpc_id,
            region=region,
            account=CNAAWSAccountRoleARNs(
                name="acc",
                cna=CNAAWSSpecV1(defaultRoleARN=arn, moduleRoleARNS=None),
            ),
        ),
        defaults=None,
        overrides=CNARDSInstanceOverridesV1(
            name=db_name,
            engine=engine,
            engine_version=engine_version,
            allocated_storage=allocated_storage,
            max_allocated_storage=max_allocated_storage,
            instance_class=instance_class,
            db_subnet_group_name=db_subnet_group_name,
            username=None,
            backup_retention_period=backup_retention_period,
        ),
    )
    asset = AWSRDSAsset.from_query_class(query_asset)
    assert isinstance(asset, AWSRDSAsset)
    assert asset.name == asset_identifier
    assert asset.region == region
    assert asset.identifier == db_name
    assert asset.vpc_id == vpc_id
    assert asset.db_subnet_group_name == db_subnet_group_name
    assert asset.instance_class == instance_class
    assert asset.engine == engine
    assert asset.engine_version == engine_version
    assert asset.allocated_storage == str(allocated_storage)
    assert asset.max_allocated_storage == str(max_allocated_storage)
    assert asset.role_arn == arn
    assert asset.backup_retention_period == backup_retention_period


def test_from_query_class_db_name_default():
    asset_identifier = "identifier"
    query_asset = CNARDSInstanceV1(
        provider=AWSRDSAsset.provider(),
        identifier="identifier",
        vpc=AWSVPCV1(
            vpc_id="vpc-id",
            region="region",
            account=CNAAWSAccountRoleARNs(
                name="acc",
                cna=CNAAWSSpecV1(defaultRoleARN="arn", moduleRoleARNS=None),
            ),
        ),
        defaults=None,
        overrides=CNARDSInstanceOverridesV1(
            name=None,
            engine="postgres",
            engine_version="14.2",
            allocated_storage=10,
            max_allocated_storage=20,
            instance_class="instance-class",
            db_subnet_group_name="db-subnet-group-name",
            username=None,
            backup_retention_period=7,
        ),
    )
    asset = AWSRDSAsset.from_query_class(query_asset)
    assert isinstance(asset, AWSRDSAsset)
    assert asset.identifier == asset_identifier
