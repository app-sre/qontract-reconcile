from reconcile.cna.assets.null import NullAsset
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetV1,
)
import json


def test_from_query_class():
    identifier = "name"
    addr_block = "addr_block"
    query_asset = CNANullAssetV1(
        provider=NullAsset.provider(),
        identifier=identifier,
        overrides=json.dumps(
            {
                "addr_block": addr_block,
            }
        ),
        defaults=None,
    )
    asset = NullAsset.from_query_class(query_asset)
    assert isinstance(asset, NullAsset)
    assert asset.name == identifier
    assert asset.addr_block == addr_block


def test_from_query_class_no_overrides():
    identifier = "name"
    query_asset = CNANullAssetV1(
        provider=NullAsset.provider(),
        identifier=identifier,
        overrides=None,
        defaults=None,
    )
    asset = NullAsset.from_query_class(query_asset)
    assert isinstance(asset, NullAsset)
    assert asset.name == identifier
    assert asset.addr_block is None
