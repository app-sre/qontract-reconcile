import logging
from typing import Any
from reconcile.cna.assets.asset import (
    Asset,
    AssetType,
    AssetTypeMetadata,
    AssetTypeVariable,
    AssetTypeVariableType,
    asset_type_by_id,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


class CNAClient:
    """
    Client used to interact with CNA. CNA API doc can be found here:
    https://gitlab.cee.redhat.com/service/cna-management/-/blob/main/openapi/openapi.yaml#/
    """

    def __init__(self, ocm_client: OCMBaseClient):
        self._ocm_client = ocm_client
        self._metadata = self._init_metadata()

    def _init_metadata(self) -> dict[AssetType, AssetTypeMetadata]:
        asset_types_metadata: dict[AssetType, AssetTypeMetadata] = {}
        for asset_type_ref in self._ocm_client.get(
            api_path="/api/cna-management/v1/asset_types"
        )["items"]:
            raw_asset_type_metadata = self._ocm_client.get(
                api_path=asset_type_ref["href"]
            )
            asset_type = asset_type_by_id(raw_asset_type_metadata["id"])
            if asset_type:
                asset_types_metadata[asset_type] = AssetTypeMetadata(
                    id=asset_type,
                    bindable=raw_asset_type_metadata.get("bindable", False),
                    variables={
                        AssetTypeVariable(
                            name=var["name"],
                            optional=var.get("default") is not None,
                            type=AssetTypeVariableType(var["type"]),
                            default=var.get("default"),
                        )
                        for var in raw_asset_type_metadata.get("variables", [])
                    },
                )

        return asset_types_metadata

    def get_asset_type_metadata(self, asset_type: AssetType) -> AssetTypeMetadata:
        return self._metadata[asset_type]

    def list_assets(self) -> list[dict[str, Any]]:
        """
        We use this to fetch the current real-world state
        of our assets
        """
        # TODO: properly handle paging
        cnas = self._ocm_client.get(api_path="/api/cna-management/v1/cnas")
        return cnas.get("items", [])

    def create(self, asset: Asset, dry_run: bool = False):
        if dry_run:
            logging.info(
                "CREATE %s %s %s",
                asset.asset_type().value,
                asset.name,
                asset.raw_asset_parameters(True),
            )
            return
        self._ocm_client.post(
            api_path="/api/cna-management/v1/cnas",
            data=asset.api_payload(),
        )

    def delete(self, asset: Asset, dry_run: bool = False):
        if dry_run:
            logging.info("DELETE %s", asset)
            return
        if asset.href:
            self._ocm_client.delete(
                api_path=asset.href,
            )

    def update(self, asset: Asset, dry_run: bool = False):
        if dry_run:
            logging.info("UPDATE %s", asset)
            return
        if asset.href:
            self._ocm_client.patch(
                api_path=asset.href,
                data=asset.api_payload(),
            )
