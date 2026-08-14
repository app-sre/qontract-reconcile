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
    # fully-formed requestedTerms payload for create_agreement_request, i.e. a
    # list of {"id": ..., "configuration": {...}?} entries.
    requested_terms: list[dict[str, Any]]


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiMarketplace:
    _hooks: Hooks

    def __init__(
        self,
        agreement_client: Any,
        discovery_client: Any,
        hooks: Hooks | None = None,  # ruff: ignore[unused-method-argument]
    ) -> None:
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
                {"name": "PartyType", "values": ["Acceptor"]},
                {"name": "AgreementType", "values": ["PurchaseAgreement"]},
                {"name": "ResourceIdentifier", "values": [ROSA_HCP_PRODUCT_ID]},
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

        offer_id = next(
            (
                entity["offer"]["offerId"]
                for entity in options[0].get("associatedEntities", [])
                if entity.get("offer", {}).get("offerId")
            ),
            options[0].get("purchaseOptionId"),
        )
        if not offer_id:
            msg = "Could not determine offer ID for ROSA HCP product"
            raise RuntimeError(msg)

        offer = self.discovery_client.get_offer(offerId=offer_id)
        agreement_proposal_id = offer.get("agreementProposalId")
        if not agreement_proposal_id:
            msg = f"No agreementProposalId found for offer {offer_id}"
            raise RuntimeError(msg)

        terms_resp = self.discovery_client.get_offer_terms(offerId=offer_id)
        requested_terms = self._build_requested_terms(terms_resp.get("offerTerms", []))
        if not requested_terms:
            msg = f"No terms found for ROSA HCP offer {offer_id}"
            raise RuntimeError(msg)

        return RosaOffer(
            offer_id=offer_id,
            agreement_proposal_id=agreement_proposal_id,
            requested_terms=requested_terms,
        )

    @classmethod
    def _build_requested_terms(
        cls,
        offer_terms: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the create_agreement_request requestedTerms payload.

        AWS requires *all* mandatory offer terms to be accepted, and the
        configurable pricing / renewal terms must carry a configuration:

        - configurableUpfrontPricingTerm: accepted with zero committed
          quantities (dimensionValue 0) so there is no upfront/contract spend;
          all consumption is billed via the usageBasedPricingTerm.
        - renewalTerm: accepted with auto-renew enabled.
        - every other term (usage/legal/support/validity/...) is accepted by id.
        """
        requested_terms: list[dict[str, Any]] = []
        for term_wrapper in offer_terms:
            for term_type, term_data in term_wrapper.items():
                if not isinstance(term_data, dict) or "id" not in term_data:
                    continue
                requested: dict[str, Any] = {"id": term_data["id"]}
                if term_type == "renewalTerm":
                    requested["configuration"] = {
                        "renewalTermConfiguration": {"enableAutoRenew": True}
                    }
                elif term_type == "configurableUpfrontPricingTerm":
                    requested["configuration"] = {
                        "configurableUpfrontPricingTermConfiguration": (
                            cls._build_upfront_config(term_data)
                        )
                    }
                requested_terms.append(requested)
        return requested_terms

    @staticmethod
    def _build_upfront_config(term_data: dict[str, Any]) -> dict[str, Any]:
        """Zero-commitment configuration for a configurableUpfrontPricingTerm.

        Uses the term's first rate card selector and lists every dimension with
        a committed quantity of 0.
        """
        rate_cards = term_data.get("rateCards") or []
        if not rate_cards:
            msg = "configurableUpfrontPricingTerm has no rateCards"
            raise RuntimeError(msg)
        rate_card = rate_cards[0]
        selector_value = (rate_card.get("selector") or {}).get("value")
        if not selector_value:
            msg = "configurableUpfrontPricingTerm rateCard has no selector value"
            raise RuntimeError(msg)
        dimensions = [
            {"dimensionKey": d["dimensionKey"], "dimensionValue": 0}
            for d in rate_card.get("rateCard") or []
            if "dimensionKey" in d
        ]
        if not dimensions:
            msg = "configurableUpfrontPricingTerm rateCard has no dimensions"
            raise RuntimeError(msg)
        return {"selectorValue": selector_value, "dimensions": dimensions}

    @invoke_with_hooks(
        lambda: AWSApiCallContext(
            method="subscribe_rosa", service="marketplace-agreement"
        )
    )
    def subscribe_rosa(
        self, agreement_proposal_id: str, requested_terms: list[dict[str, Any]]
    ) -> str:
        create_resp = self.agreement_client.create_agreement_request(
            agreementProposalIdentifier=agreement_proposal_id,
            intent="NEW",
            requestedTerms=requested_terms,
        )
        agreement_request_id = create_resp["agreementRequestId"]

        accept_resp = self.agreement_client.accept_agreement_request(
            agreementRequestId=agreement_request_id,
        )
        return accept_resp.get("agreementId", agreement_request_id)
