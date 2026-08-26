from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

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


# Typed boundary models for the raw marketplace-discovery responses. Fields use
# the AWS wire-format aliases so raw responses parse via Model(**raw), matching
# the pattern in the sibling aws_api_typed modules.
class MarketplaceOffer(BaseModel):
    offer_id: str | None = Field(None, alias="offerId")


class AssociatedEntity(BaseModel):
    offer: MarketplaceOffer | None = None


class PurchaseOption(BaseModel):
    purchase_option_id: str | None = Field(None, alias="purchaseOptionId")
    available_from_time: datetime | None = Field(None, alias="availableFromTime")
    expiration_time: datetime | None = Field(None, alias="expirationTime")
    associated_entities: list[AssociatedEntity] = Field(
        default_factory=list, alias="associatedEntities"
    )


class RateCardSelector(BaseModel):
    value: str | None = None


class RateCardDimension(BaseModel):
    dimension_key: str | None = Field(None, alias="dimensionKey")


class RateCard(BaseModel):
    selector: RateCardSelector | None = None
    # AWS names the dimension list "rateCard" inside each rate card entry.
    dimensions: list[RateCardDimension] = Field(default_factory=list, alias="rateCard")


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
        options_raw = resp.get("purchaseOptions", [])
        if not options_raw:
            msg = "No purchase options found for ROSA HCP product"
            raise RuntimeError(msg)
        options = [PurchaseOption(**o) for o in options_raw]

        # list_purchase_options returns *all* purchase options for the product,
        # including expired / not-yet-available offers, in no guaranteed order.
        # Picking the first one blindly can select a rotated-out offer whose
        # agreementProposalId is inactive, so create_agreement_request then
        # fails with "Provided agreement proposal is inactive". Select the
        # currently-active offer instead.
        option = self._select_active_purchase_option(options)

        offer_id = next(
            (
                entity.offer.offer_id
                for entity in option.associated_entities
                if entity.offer and entity.offer.offer_id
            ),
            option.purchase_option_id,
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

    @staticmethod
    def _select_active_purchase_option(
        options: list[PurchaseOption],
    ) -> PurchaseOption:
        """Select the currently-active purchase option.

        AWS returns every purchase option for the product — including offers
        that have already expired or are not yet available — with no guaranteed
        ordering. An option is active when its availability window
        (availableFromTime .. expirationTime) contains 'now'; boto3 returns
        these as timezone-aware datetimes. When several are active, prefer the
        most recently available one.
        """
        now = datetime.now(UTC)
        active = [
            o
            for o in options
            if (o.available_from_time is None or o.available_from_time <= now)
            and (o.expiration_time is None or o.expiration_time > now)
        ]
        if not active:
            msg = "No active purchase options found for ROSA HCP product"
            raise RuntimeError(msg)
        return max(
            active,
            key=lambda o: o.available_from_time or datetime.min.replace(tzinfo=UTC),
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

    @classmethod
    def _build_upfront_config(cls, term_data: dict[str, Any]) -> dict[str, Any]:
        """Zero-commitment configuration for a configurableUpfrontPricingTerm.

        A term can offer several rate cards — one per contract-duration selector
        (e.g. P12M / P24M / P36M) — in no guaranteed order. Pick deterministically
        (shortest committed duration) rather than positionally, and list every
        dimension with a committed quantity of 0 so there is no upfront spend
        regardless of the duration chosen.
        """
        rate_cards_raw = term_data.get("rateCards") or []
        if not rate_cards_raw:
            msg = "configurableUpfrontPricingTerm has no rateCards"
            raise RuntimeError(msg)
        rate_cards = [RateCard(**rc) for rc in rate_cards_raw]
        rate_card = cls._select_rate_card(rate_cards)
        # _select_rate_card guarantees a selector value and >=1 dimension.
        selector_value = rate_card.selector.value if rate_card.selector else None
        if not selector_value:
            msg = "configurableUpfrontPricingTerm rateCard has no selector value"
            raise RuntimeError(msg)
        dimensions = [
            {"dimensionKey": d.dimension_key, "dimensionValue": 0}
            for d in rate_card.dimensions
            if d.dimension_key
        ]
        return {"selectorValue": selector_value, "dimensions": dimensions}

    @classmethod
    def _select_rate_card(cls, rate_cards: list[RateCard]) -> RateCard:
        """Deterministically pick the shortest-duration usable rate card.

        A rate card is usable only if it carries both a selector value and at
        least one dimension; among the usable ones the shortest contract
        duration wins (ties broken by the selector string for stability). When
        none are usable, raise the most specific error for diagnostics.
        """
        usable: list[tuple[RateCard, str]] = []
        for rc in rate_cards:
            value = rc.selector.value if rc.selector else None
            if value and any(d.dimension_key for d in rc.dimensions):
                usable.append((rc, value))
        if not usable:
            has_selector = any(rc.selector and rc.selector.value for rc in rate_cards)
            msg = (
                "configurableUpfrontPricingTerm rateCard has no dimensions"
                if has_selector
                else "configurableUpfrontPricingTerm rateCard has no selector value"
            )
            raise RuntimeError(msg)
        rate_card, _ = min(
            usable,
            key=lambda t: (cls._duration_months(t[1]), t[1]),
        )
        return rate_card

    @staticmethod
    def _duration_months(value: str) -> int:
        """Months in an ISO-8601 duration selector (e.g. P12M, P1Y, P1Y6M).

        Unparseable selectors sort last so a recognizable duration is always
        preferred when one exists.
        """
        m = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?", value)
        if not m or not (m.group(1) or m.group(2)):
            return 10**9
        return int(m.group(1) or 0) * 12 + int(m.group(2) or 0)

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
