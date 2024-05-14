from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
import requests
from pytest_httpserver import HTTPServer
from pytest_mock import MockerFixture
from requests import HTTPError

from tools.cli_commands.cost_report.cost_management_api import CostManagementApi
from tools.cli_commands.cost_report.response import (
    AwsReportCostResponse,
    CostResponse,
    CostTotalResponse,
    DeltaResponse,
    MoneyResponse,
    OpenShiftCostOptimizationReportResponse,
    OpenShiftCostOptimizationResponse,
    OpenShiftCostResponse,
    OpenShiftReportCostResponse,
    ProjectCostResponse,
    ProjectCostValueResponse,
    RecommendationEngineResponse,
    RecommendationEnginesResponse,
    RecommendationResourcesResponse,
    RecommendationsResponse,
    RecommendationTermResponse,
    RecommendationTermsResponse,
    ReportMetaResponse,
    ResourceConfigResponse,
    ResourceResponse,
    ServiceCostResponse,
    ServiceCostValueResponse,
    TotalMetaResponse,
)
from tools.cli_commands.test.conftest import COST_REPORT_SECRET


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    return mocker.patch(
        "tools.cli_commands.cost_report.cost_management_api.OAuth2BackendApplicationSession",
        autospec=True,
    )


@pytest.fixture
def base_url(httpserver: HTTPServer) -> str:
    return httpserver.url_for("")


TOKEN_URL = "token_url"
CLIENT_ID = COST_REPORT_SECRET["client_id"]
CLIENT_SECRET = COST_REPORT_SECRET["client_secret"]
SCOPE = ["scope"]


def test_cost_management_api_create_from_secret(
    mock_session: Any,
) -> None:
    api = CostManagementApi.create_from_secret(COST_REPORT_SECRET)

    assert api.host == COST_REPORT_SECRET["api_base_url"]
    assert api.session == mock_session.return_value
    mock_session.assert_called_once_with(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_url=TOKEN_URL,
        scope=SCOPE,
    )


def test_cost_management_api_init(mock_session: Any, base_url: str) -> None:
    with CostManagementApi(
        base_url=base_url,
        token_url=TOKEN_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope=SCOPE,
    ) as api:
        pass

    assert api.host == base_url
    assert api.session == mock_session.return_value

    mock_session.assert_called_once_with(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_url=TOKEN_URL,
        scope=SCOPE,
    )
    assert mock_session.return_value.mount.call_count == 2
    mock_session.return_value.close.assert_called_once_with()


@pytest.fixture
def cost_management_api(mock_session: Any, base_url: str) -> CostManagementApi:
    # swap to requests.request to skip oauth2 logic
    mock_session.return_value.request.side_effect = requests.request
    return CostManagementApi(
        base_url=base_url,
        token_url=TOKEN_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope=SCOPE,
    )


EXPECTED_REPORT_COST_RESPONSE = AwsReportCostResponse(
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


def test_get_aws_costs_report(
    cost_management_api: CostManagementApi, fx: Callable, httpserver: HTTPServer
) -> None:
    response_body = fx("aws_cost_report.json")
    httpserver.expect_request(
        "/reports/aws/costs/",
        query_string={
            "cost_type": "calculated_amortized_cost",
            "delta": "cost",
            "filter[resolution]": "monthly",
            "filter[tag:app]": "test",
            "filter[time_scope_units]": "month",
            "filter[time_scope_value]": "-2",
            "group_by[service]": "*",
        },
    ).respond_with_data(response_body)

    report_cost_response = cost_management_api.get_aws_costs_report(app="test")

    assert report_cost_response == EXPECTED_REPORT_COST_RESPONSE


def test_get_aws_costs_report_error(
    cost_management_api: CostManagementApi,
    fx: Callable,
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/reports/aws/costs/").respond_with_data(status=500)

    with pytest.raises(HTTPError) as error:
        cost_management_api.get_aws_costs_report(app="test")

    assert error.value.response.status_code == 500


EXPECTED_OPENSHIFT_REPORT_COST_RESPONSE = OpenShiftReportCostResponse(
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
        OpenShiftCostResponse(
            date="2024-02",
            projects=[
                ProjectCostResponse(
                    project="some-project",
                    values=[
                        ProjectCostValueResponse(
                            delta_percent=10,
                            delta_value=Decimal(100),
                            clusters=["some-cluster"],
                            cost=CostTotalResponse(
                                total=MoneyResponse(
                                    value=Decimal(1000),
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


def test_get_openshift_costs_report(
    cost_management_api: CostManagementApi,
    fx: Callable,
    httpserver: HTTPServer,
) -> None:
    response_body = fx("openshift_cost_report.json")
    project = "some-project"
    cluster = "some-cluster-uuid"
    httpserver.expect_request(
        "/reports/openshift/costs/",
        query_string={
            "delta": "cost",
            "filter[resolution]": "monthly",
            "filter[cluster]": cluster,
            "filter[exact:project]": project,
            "filter[time_scope_units]": "month",
            "filter[time_scope_value]": "-2",
            "group_by[project]": "*",
        },
    ).respond_with_data(response_body)

    report_cost_response = cost_management_api.get_openshift_costs_report(
        cluster=cluster,
        project=project,
    )

    assert report_cost_response == EXPECTED_OPENSHIFT_REPORT_COST_RESPONSE


def test_get_openshift_costs_report_error(
    cost_management_api: CostManagementApi,
    fx: Callable,
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/reports/openshift/costs/").respond_with_data(status=500)

    with pytest.raises(HTTPError) as error:
        cost_management_api.get_openshift_costs_report(
            cluster="some-cluster",
            project="some-project",
        )

    assert error.value.response.status_code == 500


EXPECTED_OPENSHIFT_COST_OPTIMIZATION_RESPONSE = OpenShiftCostOptimizationReportResponse(
    data=[
        OpenShiftCostOptimizationResponse(
            cluster_alias="some-cluster",
            cluster_uuid="some-cluster-uuid",
            container="test",
            id="id-uuid",
            project="some-project",
            workload="test-deployment",
            workload_type="deployment",
            recommendations=RecommendationsResponse(
                current=RecommendationResourcesResponse(
                    limits=ResourceResponse(
                        cpu=ResourceConfigResponse(amount=4),
                        memory=ResourceConfigResponse(amount=5, format="Gi"),
                    ),
                    requests=ResourceResponse(
                        cpu=ResourceConfigResponse(amount=1),
                        memory=ResourceConfigResponse(amount=400, format="Mi"),
                    ),
                ),
                recommendation_terms=RecommendationTermsResponse(
                    long_term=RecommendationTermResponse(),
                    medium_term=RecommendationTermResponse(),
                    short_term=RecommendationTermResponse(
                        recommendation_engines=RecommendationEnginesResponse(
                            cost=RecommendationEngineResponse(
                                config=RecommendationResourcesResponse(
                                    limits=ResourceResponse(
                                        cpu=ResourceConfigResponse(amount=5),
                                        memory=ResourceConfigResponse(
                                            amount=6, format="Gi"
                                        ),
                                    ),
                                    requests=ResourceResponse(
                                        cpu=ResourceConfigResponse(amount=3),
                                        memory=ResourceConfigResponse(
                                            amount=700, format="Mi"
                                        ),
                                    ),
                                ),
                                variation=RecommendationResourcesResponse(
                                    limits=ResourceResponse(
                                        cpu=ResourceConfigResponse(amount=1),
                                        memory=ResourceConfigResponse(
                                            amount=1, format="Gi"
                                        ),
                                    ),
                                    requests=ResourceResponse(
                                        cpu=ResourceConfigResponse(amount=2),
                                        memory=ResourceConfigResponse(
                                            amount=300, format="Mi"
                                        ),
                                    ),
                                ),
                            ),
                            performance=RecommendationEngineResponse(
                                config=RecommendationResourcesResponse(
                                    limits=ResourceResponse(
                                        cpu=ResourceConfigResponse(amount=3),
                                        memory=ResourceConfigResponse(
                                            amount=6, format="Gi"
                                        ),
                                    ),
                                    requests=ResourceResponse(
                                        cpu=ResourceConfigResponse(
                                            amount=600, format="millicores"
                                        ),
                                        memory=ResourceConfigResponse(
                                            amount=700, format="Mi"
                                        ),
                                    ),
                                ),
                                variation=RecommendationResourcesResponse(
                                    limits=ResourceResponse(
                                        cpu=ResourceConfigResponse(amount=-1),
                                        memory=ResourceConfigResponse(
                                            amount=1, format="Gi"
                                        ),
                                    ),
                                    requests=ResourceResponse(
                                        cpu=ResourceConfigResponse(
                                            amount=-400, format="millicores"
                                        ),
                                        memory=ResourceConfigResponse(
                                            amount=300, format="Mi"
                                        ),
                                    ),
                                ),
                            ),
                        )
                    ),
                ),
            ),
        )
    ]
)


def test_get_openshift_cost_optimization_report(
    cost_management_api: CostManagementApi,
    fx: Callable,
    httpserver: HTTPServer,
) -> None:
    response_body = fx("openshift_cost_optimization_report.json")
    project = "some-project"
    cluster = "some-cluster-uuid"
    httpserver.expect_request(
        "/recommendations/openshift",
        query_string={
            "cluster": cluster,
            "project": project,
        },
    ).respond_with_data(response_body)

    report_cost_response = cost_management_api.get_openshift_cost_optimization_report(
        cluster=cluster,
        project=project,
    )

    assert report_cost_response == EXPECTED_OPENSHIFT_COST_OPTIMIZATION_RESPONSE


def test_get_openshift_cost_optimization_report_error(
    cost_management_api: CostManagementApi,
    fx: Callable,
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/recommendations/openshift").respond_with_data(
        status=500
    )

    with pytest.raises(HTTPError) as error:
        cost_management_api.get_openshift_cost_optimization_report(
            cluster="some-cluster",
            project="some-project",
        )

    assert error.value.response.status_code == 500
