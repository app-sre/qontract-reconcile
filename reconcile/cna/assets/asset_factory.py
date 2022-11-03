from typing import Any, Mapping
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetV1,
    CNAssetV1,
)
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.assets.asset import Asset, AssetError


def asset_factory_from_schema(schema_asset: CNAssetV1) -> Asset:
    if isinstance(schema_asset, CNANullAssetV1):
        return NullAsset.from_query_class(schema_asset)
    else:
        raise AssetError(f"Unknown schema asset type {schema_asset}")


def asset_factory_from_raw_data(data_asset: Mapping[str, Any]) -> Asset:
    asset_type = data_asset.get("asset_type")
    if asset_type == "null":
        return NullAsset.from_api_mapping(data_asset)
    else:
        raise AssetError(f"Unknown data asset type {data_asset}")
