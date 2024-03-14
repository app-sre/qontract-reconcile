import json
from typing import Callable

import httpretty as httpretty_module
import pytest
from requests import HTTPError

from reconcile.utils.prometheus import (
    PrometheusHttpQuerier,
    PrometheusQueryError,
    PrometheusValue,
    PrometheusVector,
)


def test_prometheus_vector() -> None:
    vector = PrometheusVector(
        metric={
            "__name__": "vector_name",
            "label1": "value1",
            "label2": "value2",
        },
        value=PrometheusValue(0.0, 1.0),
    )
    assert vector.name == "vector_name"
    assert vector.timestamp == 0.0
    assert vector.value == 1
    assert vector.mandatory_label("label1") == "value1"
    assert vector.label("label1") == "value1"
    assert vector.label("label3", "default") == "default"
    assert vector.label("label3") is None
    assert vector.label("label3", None) is None

    with pytest.raises(KeyError):
        vector.mandatory_label("label3")


@pytest.fixture
def prometheus_http_querier() -> PrometheusHttpQuerier:
    return PrometheusHttpQuerier(
        query_url="http://my-prometheus/api/v1/query",
        auth_token="1234567890",
    )


def build_metric(labels: dict[str, str], timestamp: float, value: str) -> dict:
    return {
        "metric": labels,
        "value": [
            timestamp,
            value,
        ],
    }


PrometheusResponseBuilder = Callable[[int, str, str, list[dict]], None]


@pytest.fixture
def prometheus_response_builder(
    prometheus_http_querier: PrometheusHttpQuerier, httpretty: httpretty_module
) -> PrometheusResponseBuilder:
    def build_response(
        http_status: int, status: str, result_type: str, metrics: list[dict]
    ) -> None:
        httpretty.register_uri(
            httpretty.GET,
            prometheus_http_querier.query_url,
            status=http_status,
            body=json.dumps({
                "status": status,
                "data": {"resultType": result_type, "result": metrics},
            }),
            content_type="text/json",
        )

    return build_response


def test_http_querier_instant_vector_query(
    prometheus_http_querier: PrometheusHttpQuerier,
    prometheus_response_builder: PrometheusResponseBuilder,
) -> None:
    prometheus_response_builder(
        200,
        "success",
        "vector",
        [
            build_metric(
                {"__name__": "vector_name", "label1": "value1", "label2": "value2"},
                15.0,
                "42",
            ),
        ],
    )

    vectors = prometheus_http_querier.instant_vector_query("query")
    assert len(vectors) == 1
    assert vectors[0].name == "vector_name"
    assert vectors[0].timestamp == 15.0
    assert vectors[0].value == 42


def test_http_querier_instant_vector_query_non_vector_result(
    prometheus_http_querier: PrometheusHttpQuerier,
    prometheus_response_builder: PrometheusResponseBuilder,
) -> None:
    prometheus_response_builder(200, "success", "matrix", [])

    with pytest.raises(PrometheusQueryError):
        prometheus_http_querier.instant_vector_query("query")


def test_http_querier_instant_vector_query_result_error(
    prometheus_http_querier: PrometheusHttpQuerier,
    prometheus_response_builder: PrometheusResponseBuilder,
) -> None:
    prometheus_response_builder(200, "error", "vector", [])

    with pytest.raises(PrometheusQueryError):
        prometheus_http_querier.instant_vector_query("query")


def test_http_querier_instant_vector_query_http_error(
    prometheus_http_querier: PrometheusHttpQuerier,
    prometheus_response_builder: PrometheusResponseBuilder,
) -> None:
    prometheus_response_builder(500, "error", "vector", [])

    with pytest.raises(HTTPError):
        prometheus_http_querier.instant_vector_query("query")
