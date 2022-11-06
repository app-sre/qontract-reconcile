from typing import Any, Mapping, Type

from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNAssetV1,
)
from reconcile.cna.assets.asset import (
    Asset,
    AssetType,
    UnknownAssetTypeError,
    asset_type_from_raw_asset,
)


_ASSET_TYPE_SCHEME: dict[AssetType, Type[Asset]] = {}
_PROVIDER_SCHEME: dict[str, Type[Asset]] = {}


def register_asset_dataclass(asset_dataclass: Type[Asset]) -> None:
    _ASSET_TYPE_SCHEME[asset_dataclass.asset_type()] = asset_dataclass
    _PROVIDER_SCHEME[asset_dataclass.provider()] = asset_dataclass


def _dataclass_for_asset_type(asset_type: AssetType) -> Type[Asset]:
    if asset_type in _ASSET_TYPE_SCHEME:
        return _ASSET_TYPE_SCHEME[asset_type]
    raise UnknownAssetTypeError(f"Unknown asset type {asset_type}")


def _dataclass_for_provider(provider: str) -> Type[Asset]:
    return _PROVIDER_SCHEME[provider]


def asset_type_for_provider(provider: str) -> AssetType:
    return _dataclass_for_provider(provider).asset_type()


def asset_factory_from_schema(schema_asset: CNAssetV1) -> Asset:
    cna_dataclass = _dataclass_for_provider(schema_asset.provider)
    return cna_dataclass.from_query_class(schema_asset)


def asset_factory_from_raw_data(raw_asset: Mapping[str, Any]) -> Asset:
    asset_type = asset_type_from_raw_asset(raw_asset)
    if asset_type:
        cna_dataclass = _dataclass_for_asset_type(asset_type)
        return Asset.from_api_mapping(raw_asset, cna_dataclass)
    raise UnknownAssetTypeError(f"Unknown asset type found in {raw_asset}")
