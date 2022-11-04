from typing import Any, Optional
from collections.abc import Mapping
from typing import Any

from reconcile.cna.assets.asset import (
    Asset,
    AssetError,
)
from reconcile.cna.assets.null import NullAsset
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetV1,
    CNAAssumeRoleAssetV1,
    CNAssetV1,
)
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.assets.aws_assume_role import AWSAssumeRoleAsset
from reconcile.cna.assets.asset import Asset, AssetError, AssetType


def asset_factory_from_schema(schema_asset: CNAssetV1) -> Asset:
    if isinstance(schema_asset, CNANullAssetV1):
        return NullAsset.from_query_class(schema_asset)
    elif isinstance(schema_asset, CNAAssumeRoleAssetV1):
        return AWSAssumeRoleAsset.from_query_class(schema_asset)
    else:
        raise AssetError(f"Unknown schema asset type {schema_asset}")


def asset_factory_from_raw_data(data_asset: Mapping[str, Any]) -> Optional[Asset]:
    asset_type = data_asset.get("asset_type")
    if asset_type == AssetType.NULL.value:
        return NullAsset.from_api_mapping(data_asset)
    elif asset_type == AssetType.EXAMPLE_AWS_ASSUMEROLE.value:
        return AWSAssumeRoleAsset.from_api_mapping(data_asset)
    else:
        href = data_asset.get("href")
        logging.warning(
            f"Ignoring unknown data asset type '{asset_type}' - href: {href}"
        )
        return None
