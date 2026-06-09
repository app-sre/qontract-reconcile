"""OPA sidecar authorization client for qontract-api."""

import re
import time
from typing import Any

import httpxyz as httpx
from fastapi import HTTPException, status
from prometheus_client import Counter, Histogram

from qontract_api.logger import get_logger

logger = get_logger(__name__)

opa_decision_duration = Histogram(
    "qontract_api_opa_decision_duration_seconds",
    "OPA authorization decision latency",
    labelnames=["obj"],
)

opa_decisions_total = Counter(
    "qontract_api_opa_decisions_total",
    "Total OPA authorization decisions",
    labelnames=["result", "obj"],
)


def flatten_params(data: dict[str, Any], *, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict to dot-notation for OPA parameter matching.

    Converts nested structures like {"secret": {"path": "x"}} to
    {"secret.path": "x"} so OPA's valid_params regex matching works
    uniformly across query params and POST body fields.
    """
    result: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        match value:
            case dict():
                result.update(flatten_params(value, prefix=full_key))
            case list():
                pass
            case None:
                pass
            case _:
                result[full_key] = str(value)
    return result


class OPAClient:
    """HTTP client for querying OPA sidecar authorization decisions."""

    def __init__(
        self,
        *,
        opa_url: str,
        skip_endpoints: list[re.Pattern[str]],
        client: httpx.AsyncClient,
    ) -> None:
        self.opa_url = opa_url
        self.skip_endpoints = skip_endpoints
        self.client = client

    def should_skip(self, path: str) -> bool:
        """Check if the endpoint should skip OPA authorization."""
        return any(pattern.match(path) for pattern in self.skip_endpoints)

    async def authorize(
        self,
        *,
        username: str,
        obj: str,
        params: dict[str, str],
        request_id: str = "",
    ) -> None:
        """Query OPA and raise HTTP 403 on denial or error (fail-closed)."""
        start = time.monotonic()
        data: dict[str, Any] = {
            "input": {
                "username": username,
                "obj": obj,
                "params": params,
                "request_id": request_id,
            }
        }

        try:
            response = await self.client.post(self.opa_url, json=data)
        except Exception as e:
            duration = time.monotonic() - start
            opa_decision_duration.labels(obj=obj).observe(duration)
            logger.exception(
                "OPA authorization failed (fail-closed)",
                username=username,
                operation=obj,
            )
            opa_decisions_total.labels(result="error", obj=obj).inc()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
            ) from e

        duration = time.monotonic() - start
        opa_decision_duration.labels(obj=obj).observe(duration)

        if response.status_code != status.HTTP_200_OK:
            logger.error(
                "OPA returned unexpected status (fail-closed)",
                username=username,
                operation=obj,
                opa_status=response.status_code,
            )
            opa_decisions_total.labels(result="error", obj=obj).inc()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        opa_result = response.json().get("result", {})

        if not opa_result.get("authorized"):
            logger.warning(
                "OPA authorization denied",
                username=username,
                operation=obj,
                params=params,
            )
            opa_decisions_total.labels(result="deny", obj=obj).inc()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        opa_decisions_total.labels(result="allow", obj=obj).inc()
