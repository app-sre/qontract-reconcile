from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3
import pytest
from botocore.stub import Stubber
from qontract_utils.aws_api_typed.marketplace import (
    ROSA_HCP_PRODUCT_ID,
    AWSApiMarketplace,
    RosaOffer,
)
from qontract_utils.hooks import Hooks

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from botocore.client import BaseClient
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
        filters=[
            {"name": "PartyType", "values": ["Acceptor"]},
            {"name": "AgreementType", "values": ["PurchaseAgreement"]},
            {"name": "ResourceIdentifier", "values": [ROSA_HCP_PRODUCT_ID]},
        ],
    )


def test_has_rosa_subscription_false(
    marketplace_api: AWSApiMarketplace, agreement_client: MagicMock
) -> None:
    agreement_client.search_agreements.return_value = {"agreementViewSummaries": []}
    assert marketplace_api.has_rosa_subscription() is False


def test_discover_rosa_offer(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {
        "purchaseOptions": [
            {
                "purchaseOptionId": "po-123",
                "associatedEntities": [{"offer": {"offerId": "offer-abc"}}],
            }
        ]
    }
    discovery_client.get_offer.return_value = {
        "agreementProposalId": "prop-xyz",
    }
    # mirrors the real ROSA HCP offer: pay-as-you-go usage term, a mandatory
    # configurable upfront term (accepted at zero committed quantity),
    # legal/support terms, and a renewal term (auto-renew).
    discovery_client.get_offer_terms.return_value = {
        "offerTerms": [
            {
                "usageBasedPricingTerm": {
                    "id": "term-usage",
                    "type": "UsageBasedPricingTerm",
                }
            },
            {
                "configurableUpfrontPricingTerm": {
                    "id": "term-upfront",
                    "type": "ConfigurableUpfrontPricingTerm",
                    "rateCards": [
                        {
                            "selector": {"type": "Duration", "value": "P12M"},
                            "rateCard": [
                                {"dimensionKey": "control_plane", "price": "2190"},
                                {"dimensionKey": "four_vcpu_hour", "price": "1000"},
                            ],
                        }
                    ],
                }
            },
            {"legalTerm": {"id": "term-legal", "type": "LegalTerm"}},
            {"supportTerm": {"id": "term-support", "type": "SupportTerm"}},
            {"renewalTerm": {"id": "term-renewal", "type": "RenewalTerm"}},
        ]
    }

    offer = marketplace_api.discover_rosa_offer()

    # all terms accepted: upfront carries a zero-quantity configuration, renewal
    # carries auto-renew, the rest are id-only.
    assert offer == RosaOffer(
        offer_id="offer-abc",
        agreement_proposal_id="prop-xyz",
        requested_terms=[
            {"id": "term-usage"},
            {
                "id": "term-upfront",
                "configuration": {
                    "configurableUpfrontPricingTermConfiguration": {
                        "selectorValue": "P12M",
                        "dimensions": [
                            {"dimensionKey": "control_plane", "dimensionValue": 0},
                            {"dimensionKey": "four_vcpu_hour", "dimensionValue": 0},
                        ],
                    }
                },
            },
            {"id": "term-legal"},
            {"id": "term-support"},
            {
                "id": "term-renewal",
                "configuration": {
                    "renewalTermConfiguration": {"enableAutoRenew": True}
                },
            },
        ],
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
        "agreementProposalId": "prop-xyz",
    }
    discovery_client.get_offer_terms.return_value = {
        "offerTerms": [
            {"supportTerm": {"id": "term-1", "type": "SupportTerm"}},
        ]
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
        "purchaseOptions": [{"purchaseOptionId": "po-1", "associatedEntities": []}]
    }
    discovery_client.get_offer.return_value = {}
    with pytest.raises(RuntimeError, match="No agreementProposalId found"):
        marketplace_api.discover_rosa_offer()


def test_discover_rosa_offer_no_terms(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {
        "purchaseOptions": [{"purchaseOptionId": "po-1", "associatedEntities": []}]
    }
    discovery_client.get_offer.return_value = {
        "agreementProposalId": "prop-1",
    }
    discovery_client.get_offer_terms.return_value = {"offerTerms": []}
    with pytest.raises(RuntimeError, match="No terms found"):
        marketplace_api.discover_rosa_offer()


def test_discover_rosa_offer_upfront_no_dimensions(
    marketplace_api: AWSApiMarketplace, discovery_client: MagicMock
) -> None:
    discovery_client.list_purchase_options.return_value = {
        "purchaseOptions": [{"purchaseOptionId": "po-1", "associatedEntities": []}]
    }
    discovery_client.get_offer.return_value = {"agreementProposalId": "prop-1"}
    discovery_client.get_offer_terms.return_value = {
        "offerTerms": [
            {
                "configurableUpfrontPricingTerm": {
                    "id": "term-upfront",
                    "type": "ConfigurableUpfrontPricingTerm",
                    "rateCards": [
                        {
                            "selector": {"type": "Duration", "value": "P12M"},
                            "rateCard": [],
                        }
                    ],
                }
            },
        ]
    }
    with pytest.raises(RuntimeError, match="no dimensions"):
        marketplace_api.discover_rosa_offer()


def test_subscribe_rosa(
    marketplace_api: AWSApiMarketplace, agreement_client: MagicMock
) -> None:
    agreement_client.create_agreement_request.return_value = {
        "agreementRequestId": "req-123"
    }
    agreement_client.accept_agreement_request.return_value = {"agreementId": "agr-456"}

    result = marketplace_api.subscribe_rosa(
        agreement_proposal_id="prop-xyz",
        requested_terms=[
            {"id": "term-1"},
            {
                "id": "term-2",
                "configuration": {
                    "renewalTermConfiguration": {"enableAutoRenew": True}
                },
            },
        ],
    )

    assert result == "agr-456"
    agreement_client.create_agreement_request.assert_called_once_with(
        agreementProposalIdentifier="prop-xyz",
        intent="NEW",
        requestedTerms=[
            {"id": "term-1"},
            {
                "id": "term-2",
                "configuration": {
                    "renewalTermConfiguration": {"enableAutoRenew": True}
                },
            },
        ],
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
        requested_terms=[{"id": "term-1"}],
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


# The tests below drive the API against real botocore clients wrapped in a
# Stubber. Unlike the Mock-based tests above, the Stubber runs botocore's
# parameter validation against the actual service model, so any drift between
# the params we send and the AWS API (wrong key names, unknown params, missing
# required fields) fails the test instead of silently passing. This guards
# against regressions like passing `catalog`/`agreementProposalId`/`termId` to
# create_agreement_request, which Mocks accept but AWS rejects at runtime.


@pytest.fixture
def real_agreement_client() -> BaseClient:
    return boto3.client(
        "marketplace-agreement",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


def test_has_rosa_subscription_params_valid_against_botocore_model(
    real_agreement_client: BaseClient, mocker: MockerFixture
) -> None:
    api = AWSApiMarketplace(
        agreement_client=real_agreement_client, discovery_client=mocker.Mock()
    )
    stubber = Stubber(real_agreement_client)
    stubber.add_response(
        "search_agreements",
        {"agreementViewSummaries": [{"agreementId": "agr-123"}]},
        expected_params={
            "catalog": "AWSMarketplace",
            "filters": [
                {"name": "PartyType", "values": ["Acceptor"]},
                {"name": "AgreementType", "values": ["PurchaseAgreement"]},
                {"name": "ResourceIdentifier", "values": [ROSA_HCP_PRODUCT_ID]},
            ],
        },
    )
    with stubber:
        assert api.has_rosa_subscription() is True
    stubber.assert_no_pending_responses()


def test_subscribe_rosa_params_valid_against_botocore_model(
    real_agreement_client: BaseClient, mocker: MockerFixture
) -> None:
    api = AWSApiMarketplace(
        agreement_client=real_agreement_client, discovery_client=mocker.Mock()
    )
    stubber = Stubber(real_agreement_client)
    # include a term with a renewalTermConfiguration so botocore validates the
    # nested configuration union shape too, not just id-only terms.
    requested_terms: list[dict[str, Any]] = [
        {"id": "term-1"},
        {
            "id": "term-2",
            "configuration": {"renewalTermConfiguration": {"enableAutoRenew": True}},
        },
        {
            "id": "term-3",
            "configuration": {
                "configurableUpfrontPricingTermConfiguration": {
                    "selectorValue": "P12M",
                    "dimensions": [
                        {"dimensionKey": "control_plane", "dimensionValue": 0}
                    ],
                }
            },
        },
    ]
    stubber.add_response(
        "create_agreement_request",
        {"agreementRequestId": "req-123"},
        expected_params={
            "agreementProposalIdentifier": "prop-xyz",
            "intent": "NEW",
            "requestedTerms": requested_terms,
        },
    )
    stubber.add_response(
        "accept_agreement_request",
        {"agreementId": "agr-456"},
        expected_params={"agreementRequestId": "req-123"},
    )
    with stubber:
        result = api.subscribe_rosa(
            agreement_proposal_id="prop-xyz", requested_terms=requested_terms
        )
    assert result == "agr-456"
    stubber.assert_no_pending_responses()
