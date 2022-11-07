from reconcile.cna.assets.null import NullAsset
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetV1,
)


def test_from_query_class():
    name = "name"
    addr_block = "addr_block"
    query_asset = CNANullAssetV1(
        provider=NullAsset.provider(), name=name, addr_block=addr_block
    )
    asset = NullAsset.from_query_class(query_asset)
    assert isinstance(asset, NullAsset)
    assert asset.name == name
    assert asset.addr_block == addr_block
