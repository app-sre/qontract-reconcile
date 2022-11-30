import logging
from typing import Any

from reconcile.cna.assets.asset import Asset
from reconcile.utils.ocm_base_client import OCMBaseClient


class CNAClient:
    """
    Client used to interact with CNA. CNA API doc can be found here:
    https://gitlab.cee.redhat.com/service/cna-management/-/blob/main/openapi/openapi.yaml#/
    """

    def __init__(self, ocm_client: OCMBaseClient):
        self._ocm_client = ocm_client

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
            logging.info("CREATE %s", asset)
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
