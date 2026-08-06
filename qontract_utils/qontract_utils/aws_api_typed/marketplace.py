from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

ROSA_HCP_PRODUCT_ID = "bfdca560-2c78-4e64-8193-794c159e6d30"

log = logging.getLogger(__name__)


class RosaOffer(BaseModel):
    offer_id: str
    agreement_proposal_id: str
    term_ids: list[str]


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiMarketplace:
    _hooks: Hooks

    def __init__(
        self,
        agreement_client: Any,
        discovery_client: Any,
        hooks: Hooks | None = None,
    ) -> None:  # ruff: ignore[unused-method-argument]
        self.agreement_client = agreement_client
        self.discovery_client = discovery_client

    @invoke_with_hooks(
        lambda: AWSApiCallContext(
            method="has_rosa_subscription", service="marketplace-agreement"
        )
    )
    def has_rosa_subscription(self) -> bool:
        resp = self.agreement_client.search_agreements(
            catalog="AWSMarketplace",
            filters=[
                {"name": "ResourceIdentifier", "values": [ROSA_HCP_PRODUCT_ID]}
            ],
        )
        return bool(resp.get("agreementViewSummaries"))

    @invoke_with_hooks(
        lambda: AWSApiCallContext(
            method="discover_rosa_offer", service="marketplace-discovery"
        )
    )
    def discover_rosa_offer(self) -> RosaOffer:
        resp = self.discovery_client.list_purchase_options(
            filters=[
                {
                    "filterType": "PRODUCT_ID",
                    "filterValues": [ROSA_HCP_PRODUCT_ID],
                }
            ],
        )
        options = resp.get("purchaseOptions", [])
        if not options:
            msg = "No purchase options found for ROSA HCP product"
            raise RuntimeError(msg)

        offer_id = None
        for entity in options[0].get("associatedEntities", []):
            if oid := entity.get("offer", {}).get("offerId"):
                offer_id = oid
                break
        if not offer_id:
            offer_id = options[0].get("purchaseOptionId")
        if not offer_id:
            msg = "Could not determine offer ID for ROSA HCP product"
            raise RuntimeError(msg)

        offer = self.discovery_client.get_offer(offerId=offer_id)
        agreement_proposal_id = offer.get("agreementProposalIdentifier")
        if not agreement_proposal_id:
            msg = f"No agreementProposalIdentifier found for offer {offer_id}"
            raise RuntimeError(msg)

        terms_resp = self.discovery_client.get_offer_terms(offerId=offer_id)
        term_ids = [term["termId"] for term in terms_resp.get("terms", [])]
        if not term_ids:
            msg = f"No terms found for ROSA HCP offer {offer_id}"
            raise RuntimeError(msg)

        return RosaOffer(
            offer_id=offer_id,
            agreement_proposal_id=agreement_proposal_id,
            term_ids=term_ids,
        )

    @invoke_with_hooks(
        lambda: AWSApiCallContext(
            method="subscribe_rosa", service="marketplace-agreement"
        )
    )
    def subscribe_rosa(
        self, agreement_proposal_id: str, term_ids: list[str]
    ) -> str:
        create_resp = self.agreement_client.create_agreement_request(
            catalog="AWSMarketplace",
            agreementProposalIdentifier=agreement_proposal_id,
            intent="NEW",
            requestedTerms=[{"termId": tid} for tid in term_ids],
        )
        agreement_request_id = create_resp["agreementRequestId"]

        accept_resp = self.agreement_client.accept_agreement_request(
            agreementRequestId=agreement_request_id,
        )
        return accept_resp.get("agreementId", agreement_request_id)
