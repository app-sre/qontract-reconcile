from typing import NamedTuple, Protocol

import requests
from pydantic import BaseModel, Field

from reconcile.gql_definitions.fragments.prometheus_instance import (
    PrometheusInstance,
    PrometheusInstanceBearerAuthV1,
    PrometheusInstanceOidcAuthV1,
)
from reconcile.utils.secret_reader import SecretReaderBase

INSTANT_VECTOR_RESULT_TYPE = "vector"


class PrometheusQueryError(Exception):
    pass


class PrometheusValue(NamedTuple):
    timestamp: float
    value: float


class PrometheusVector(BaseModel):
    metric: dict[str, str]
    raw_value: PrometheusValue = Field(..., alias="value")

    @property
    def name(self) -> str:
        return self.metric["__name__"]

    @property
    def timestamp(self) -> float:
        return self.raw_value[0]

    @property
    def value(self) -> float:
        return self.raw_value[1]

    def mandatory_label(self, label_name: str) -> str:
        return self.metric[label_name]

    def label(self, label_name: str, default: str | None = None) -> str | None:
        return self.metric.get(label_name, default)


class PrometheusQuerier(Protocol):
    """
    A protocol for a querier of Prometheus.
    """

    def instant_vector_query(self, query: str) -> list[PrometheusVector]:
        """
        Query for instant vectors.
        """


class PrometheusHttpQuerier(BaseModel):
    query_url: str
    auth_token: str

    def instant_vector_query(self, query: str) -> list[PrometheusVector]:
        response = requests.get(
            self.query_url,
            params={"query": query},
            headers={
                "Authorization": f"Bearer {self.auth_token}",
            },
        )

        response.raise_for_status()

        # Parse the response JSON
        try:
            parsed = response.json()
        except Exception as e:
            raise PrometheusQueryError(
                f"Query failed with invalid JSON response: {response.text[:100]}..."
            ) from e
        if parsed.get("status") != "success":
            raise PrometheusQueryError(
                f"Query response status was not `success`but {parsed.get('status')}"
            )
        if "data" not in parsed:
            raise PrometheusQueryError(
                f"Query response does not contain `data`: {response.text[:100]}..."
            )
        result_type = parsed.get("data", {}).get("resultType")
        if result_type != INSTANT_VECTOR_RESULT_TYPE:
            raise PrometheusQueryError(
                f"Query failed with unexpected result type. Expected {INSTANT_VECTOR_RESULT_TYPE} got {result_type}"
            )
        return [PrometheusVector(**m) for m in parsed["data"]["result"]]


def init_prometheus_http_querier_from_prometheus_instance(
    prometheus: PrometheusInstance, secret_reader: SecretReaderBase
) -> PrometheusHttpQuerier:
    match prometheus.auth:
        case PrometheusInstanceBearerAuthV1():
            auth_token = secret_reader.read_secret(prometheus.auth.token)
        case PrometheusInstanceOidcAuthV1():
            client_secret = secret_reader.read_secret(
                prometheus.auth.access_token_client_secret
            )
            data = {
                "grant_type": "client_credentials",
                "client_id": prometheus.auth.access_token_client_id,
                "client_secret": client_secret,
            }
            response = requests.post(
                prometheus.auth.access_token_url, data=data, timeout=15
            )
            response.raise_for_status()
            auth_token = response.json().get("access_token")
        case _:
            raise Exception(f"Unsupported auth type: {prometheus.auth.provider}")

    return PrometheusHttpQuerier(
        query_url=f"{prometheus.base_url}/{prometheus.query_path}",
        auth_token=auth_token,
    )
