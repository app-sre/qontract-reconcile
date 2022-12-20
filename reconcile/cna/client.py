import logging
from dataclasses import asdict
from typing import Any

from reconcile.cna.assets.asset import (
    ASSET_CREATOR_FIELD,
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

    def __init__(self, ocm_client: OCMBaseClient, init_metadata: bool = False):
        self._ocm_client = ocm_client
        self._metadata = self._init_metadata() if init_metadata else None

    def _init_metadata(self) -> dict[AssetType, AssetTypeMetadata]:
        asset_types_metadata: dict[AssetType, AssetTypeMetadata] = {}
        for asset_type_ref in self._ocm_client.get(
            api_path=self._cna_api_v1_endpoint("/asset_types")
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

    def service_account_name(self) -> str:
        account = self._ocm_client.get(api_path="/api/accounts_mgmt/v1/current_account")
        return account["username"]

    def list_assets_for_creator(self, creator_username: str) -> list[dict[str, Any]]:
        return [
            c
            for c in self.list_assets()
            if c.get(ASSET_CREATOR_FIELD, {}).get("username") == creator_username
        ]

    def list_assets(self) -> list[dict[str, Any]]:
        """
        We use this to fetch the current real-world state
        of our assets
        """
        # TODO: properly handle paging
        cnas = self._ocm_client.get(api_path=self._cna_api_v1_endpoint("/cnas"))
        return cnas.get("items", [])

    def fetch_bindings_for_asset(self, asset: Asset) -> list[dict[str, str]]:
        """
        Currently bindings can only be retrieved per asset.
        I.e., we will need one GET call per asset to aquire
        all bindings.
        """
        bindings = self._ocm_client.get(api_path=f"{asset.href}/bind")
        return bindings.get("items", [])

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
            api_path=self._cna_api_v1_endpoint("/cnas"),
            data=asset.api_payload(),
        )

    def bind(self, asset: Asset, dry_run: bool = False):
        for binding in asset.bindings:
            if dry_run:
                logging.info(
                    "BIND %s %s %s",
                    asset.asset_type().value,
                    asset.name,
                    binding,
                )
                continue
            self._ocm_client.post(
                api_path=f"{asset.href}/bind",
                data=asdict(binding),
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

    def _cna_api_v1_endpoint(self, path: str) -> str:
        return f"/api/cna-management/v1{path}"
