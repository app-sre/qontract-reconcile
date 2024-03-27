from collections.abc import Callable
from decimal import Decimal
from typing import Any, Tuple

import httpretty
import pytest
import requests
from httpretty.core import HTTPrettyRequest
from pytest_mock import MockerFixture
from requests import HTTPError

from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.response import (
    CostResponse,
    CostTotalResponse,
    DeltaResponse,
    MoneyResponse,
    ReportCostResponse,
    ReportMetaResponse,
    ServiceCostResponse,
    ServiceCostValueResponse,
    TotalMetaResponse,
)


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.cost_management_api.OAuth2BackendApplicationSession",
        autospec=True,
    )


BASE_URL = "http://base_url"
TOKEN_URL = "token_url"
CLIENT_ID = "client_id"
CLIENT_SECRET = "client_secret"
SCOPE = ["some-scope"]


def test_cost_management_api_init(
    mock_session: Any,
) -> None:
    with CostManagementApi(
        base_url=BASE_URL,
        token_url=TOKEN_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope=SCOPE,
    ) as api:
        pass

    assert api.base_url == BASE_URL
    assert api.session == mock_session.return_value

    mock_session.assert_called_once_with(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_url=TOKEN_URL,
        scope=SCOPE,
    )
    mock_session.return_value.close.assert_called_once_with()


@pytest.fixture
def cost_management_api(
    mock_session: Any,
) -> CostManagementApi:
    # swap to requests.request to skip oauth2 logic
    mock_session.return_value.request.side_effect = requests.request
    return CostManagementApi(
        base_url=BASE_URL,
        token_url=TOKEN_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope=SCOPE,
    )


EXPECTED_REPORT_COST_RESPONSE = ReportCostResponse(
    meta=ReportMetaResponse(
        delta=DeltaResponse(
            value=Decimal(100),
            percent=10,
        ),
        total=TotalMetaResponse(
            cost=CostTotalResponse(
                total=MoneyResponse(
                    value=Decimal(1000),
                    units="USD",
                )
            )
        ),
    ),
    data=[
        CostResponse(
            date="2024-02",
            services=[
                ServiceCostResponse(
                    service="AmazonEC2",
                    values=[
                        ServiceCostValueResponse(
                            delta_percent=10,
                            delta_value=Decimal(200),
                            cost=CostTotalResponse(
                                total=MoneyResponse(
                                    value=Decimal(800),
                                    units="USD",
                                )
                            ),
                        )
                    ],
                ),
                ServiceCostResponse(
                    service="AmazonS3",
                    values=[
                        ServiceCostValueResponse(
                            delta_percent=-10,
                            delta_value=Decimal(-100),
                            cost=CostTotalResponse(
                                total=MoneyResponse(
                                    value=Decimal(200),
                                    units="USD",
                                )
                            ),
                        )
                    ],
                ),
            ],
        ),
    ],
)


@httpretty.activate(allow_net_connect=False, verbose=True)
def test_get_aws_costs_report(
    cost_management_api: CostManagementApi,
    fx: Callable,
) -> None:
    response_body = fx("aws_cost_report.json")
    httpretty.register_uri(
        httpretty.GET,
        f"{BASE_URL}/reports/aws/costs/?"
        "cost_type=calculated_amortized_cost&"
        "delta=cost&"
        "filter[resolution]=monthly&"
        "filter[tag:app]=test&"
        "filter[time_scope_units]=month&"
        "filter[time_scope_value]=-2&"
        "group_by[service]=*",
        body=response_body,
        match_querystring=True,
    )

    report_cost_response = cost_management_api.get_aws_costs_report(app="test")

    assert report_cost_response == EXPECTED_REPORT_COST_RESPONSE


@httpretty.activate(allow_net_connect=False, verbose=True)
def test_get_aws_costs_report_error(
    cost_management_api: CostManagementApi,
    fx: Callable,
) -> None:
    def callback(
        _request: HTTPrettyRequest,
        _url: str,
        headers: dict,
    ) -> Tuple[int, dict, str]:
        return 500, headers, ""

    httpretty.register_uri(
        httpretty.GET,
        f"{BASE_URL}/reports/aws/costs/",
        body=callback,
    )

    with pytest.raises(HTTPError) as error:
        cost_management_api.get_aws_costs_report(app="test")

    assert error.value.response.status_code == 500
