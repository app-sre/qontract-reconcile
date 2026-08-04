from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from qontract_utils.aws_api_typed.marketplace import (
    ROSA_HCP_PRODUCT_ID,
    AWSApiMarketplace,
    RosaOffer,
)
from qontract_utils.hooks import Hooks

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture
    from qontract_utils.aws_api_typed._hooks import AWSApiCallContext


@pytest.fixture
def agreement_client(mocker: MockerFixture) -> MagicMock:
    return mocker.Mock()


@pytest.fixture
def discovery_client(mocker: MockerFixture) -> MagicMock:
    return mocker.Mock()


@pytest.fixture
def marketplace_api(
    agreement_client: MagicMock, discovery_client: MagicMock
) -> AWSApiMarketplace:
    return AWSApiMarketplace(
        agreement_client=agreement_client, discovery_client=discovery_client
    )


def test_has_rosa_subscription_true(
    marketplace_api: AWSApiMarketplace, agreement_client: MagicMock
) -> None:
    agreement_client.search_agreements.return_value = {
        "agreementViewSummaries": [{"agreementId": "agr-123"}]
    }
    assert marketplace_api.has_rosa_subscription() is True
    agreement_client.search_agreements.assert_called_once_with(
        catalog="AWSMarketplace",
        filters=[{"name": "ResourceIdentifier", "values": [ROSA_HCP_PRODUCT_ID]}],
    )


def test_has_rosa_subscription_false(
    marketplace_api: AWSApiMarketplace, agreement_client: MagicMock
) -> None:
    agreement_client.search_agreements.return_value = {
        "agreementViewSummaries": []
    }
    assert marketplace_api.has_rosa_subscription() is False


def test_discover_rosa_offer(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {
        "purchaseOptions": [
            {
                "purchaseOptionId": "po-123",
                "associatedEntities": [
                    {"offer": {"offerId": "offer-abc"}}
                ],
            }
        ]
    }
    discovery_client.get_offer.return_value = {
        "agreementProposalIdentifier": "prop-xyz",
    }
    discovery_client.get_offer_terms.return_value = {
        "terms": [{"termId": "term-1"}, {"termId": "term-2"}]
    }

    offer = marketplace_api.discover_rosa_offer()

    assert offer == RosaOffer(
        offer_id="offer-abc",
        agreement_proposal_id="prop-xyz",
        term_ids=["term-1", "term-2"],
    )
    discovery_client.list_purchase_options.assert_called_once()
    discovery_client.get_offer.assert_called_once_with(offerId="offer-abc")
    discovery_client.get_offer_terms.assert_called_once_with(offerId="offer-abc")


def test_discover_rosa_offer_fallback_to_purchase_option_id(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {
        "purchaseOptions": [
            {
                "purchaseOptionId": "po-fallback",
                "associatedEntities": [],
            }
        ]
    }
    discovery_client.get_offer.return_value = {
        "agreementProposalIdentifier": "prop-xyz",
    }
    discovery_client.get_offer_terms.return_value = {
        "terms": [{"termId": "term-1"}]
    }

    offer = marketplace_api.discover_rosa_offer()
    assert offer.offer_id == "po-fallback"
    discovery_client.get_offer.assert_called_once_with(offerId="po-fallback")


def test_discover_rosa_offer_no_purchase_options(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {"purchaseOptions": []}
    with pytest.raises(RuntimeError, match="No purchase options"):
        marketplace_api.discover_rosa_offer()


def test_discover_rosa_offer_no_proposal_id(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {
        "purchaseOptions": [
            {"purchaseOptionId": "po-1", "associatedEntities": []}
        ]
    }
    discovery_client.get_offer.return_value = {}
    with pytest.raises(RuntimeError, match="No agreementProposalIdentifier"):
        marketplace_api.discover_rosa_offer()


def test_discover_rosa_offer_no_terms(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {
        "purchaseOptions": [
            {"purchaseOptionId": "po-1", "associatedEntities": []}
        ]
    }
    discovery_client.get_offer.return_value = {
        "agreementProposalIdentifier": "prop-1",
    }
    discovery_client.get_offer_terms.return_value = {"terms": []}
    with pytest.raises(RuntimeError, match="No terms found"):
        marketplace_api.discover_rosa_offer()


def test_subscribe_rosa(
    marketplace_api: AWSApiMarketplace, agreement_client: MagicMock
) -> None:
    agreement_client.create_agreement_request.return_value = {
        "agreementRequestId": "req-123"
    }
    agreement_client.accept_agreement_request.return_value = {
        "agreementId": "agr-456"
    }

    result = marketplace_api.subscribe_rosa(
        agreement_proposal_id="prop-xyz",
        term_ids=["term-1", "term-2"],
    )

    assert result == "agr-456"
    agreement_client.create_agreement_request.assert_called_once_with(
        catalog="AWSMarketplace",
        agreementProposalIdentifier="prop-xyz",
        intent="NEW",
        requestedTerms=[{"termId": "term-1"}, {"termId": "term-2"}],
    )
    agreement_client.accept_agreement_request.assert_called_once_with(
        agreementRequestId="req-123",
    )


def test_subscribe_rosa_fallback_to_request_id(
    marketplace_api: AWSApiMarketplace, agreement_client: MagicMock
) -> None:
    agreement_client.create_agreement_request.return_value = {
        "agreementRequestId": "req-123"
    }
    agreement_client.accept_agreement_request.return_value = {}

    result = marketplace_api.subscribe_rosa(
        agreement_proposal_id="prop-xyz",
        term_ids=["term-1"],
    )
    assert result == "req-123"


def test_hooks_fire_on_method_call(
    agreement_client: MagicMock, discovery_client: MagicMock
) -> None:
    contexts: list[AWSApiCallContext] = []
    api = AWSApiMarketplace(
        agreement_client=agreement_client,
        discovery_client=discovery_client,
        hooks=Hooks(pre_hooks=[contexts.append]),
    )
    agreement_client.search_agreements.return_value = {"agreementViewSummaries": []}

    api.has_rosa_subscription()

    assert len(contexts) == 1
    assert contexts[0].method == "has_rosa_subscription"
    assert contexts[0].service == "marketplace-agreement"
