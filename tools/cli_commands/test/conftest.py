from collections.abc import Callable
from pathlib import Path

import pytest

from tools.cli_commands.cost_report.response import (
    OpenShiftCostOptimizationReportResponse,
    OpenShiftCostOptimizationResponse,
    RecommendationEngineResponse,
    RecommendationEnginesResponse,
    RecommendationResourcesResponse,
    RecommendationsResponse,
    RecommendationTermResponse,
    RecommendationTermsResponse,
    ResourceConfigResponse,
    ResourceResponse,
)


@pytest.fixture
def fx() -> Callable:
    def _fx(name: str) -> str:
        return (Path(__file__).parent / "fixtures" / name).read_text()

    return _fx


COST_MANAGEMENT_CONSOLE_BASE_URL = (
    "https://console.redhat.com/openshift/cost-management"
)

COST_REPORT_SECRET = {
    "api_base_url": "base_url",
    "token_url": "token_url",
    "client_id": "client_id",
    "client_secret": "client_secret",
    "scope": "scope",
    "console_base_url": COST_MANAGEMENT_CONSOLE_BASE_URL,
}

OPENSHIFT_COST_OPTIMIZATION_RESPONSE = OpenShiftCostOptimizationReportResponse(
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
