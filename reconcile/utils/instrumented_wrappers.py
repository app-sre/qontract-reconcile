import os
from typing import Any

from prometheus_client.core import Counter
from requests import (
    Response,
    Session,
)
from sretoolbox.container import (
    Image,
    Skopeo,
)

from reconcile.utils import metrics

# TODO: move these to a shared, constants module

INTEGRATION_NAME = os.environ.get("INTEGRATION_NAME", "")
SHARDS = int(os.environ.get("SHARDS", "1"))
SHARD_ID = int(os.environ.get("SHARD_ID", "0"))


class InstrumentedImage(Image):
    """Normal Image that exposes the count of reachouts to external
    registries.

    It helps us understand the performance of our caches and predict
    our mirroring-related costs.

    """

    def _get_manifest(self) -> Response:
        metrics.registry_reachouts.labels(
            integration=INTEGRATION_NAME,
            shard=SHARDS,
            shard_id=SHARD_ID,
            registry=self.registry,
        ).inc()
        return super()._get_manifest()


class InstrumentedSkopeo(Skopeo):
    def copy(self, *args: Any, **kwargs: Any) -> bytes | str:
        metrics.copy_count.labels(
            integration=INTEGRATION_NAME, shard=SHARDS, shard_id=SHARD_ID
        ).inc()
        return super().copy(*args, **kwargs)


class InstrumentedSession(Session):
    """
    Instrumented requests.Session that auto increments Prometheus Counter on request.

    Usage:
        from prometheus_client import Counter
        gitlab_request = Counter(
            name="qontract_reconcile_gitlab_request_total",
            documentation="Number of calls made to Gitlab API",
            labelnames=["integration"],
        )
        session = InstrumentedSession(counter.labels(integration="gitlab-housekeeping"))
    """

    def __init__(self, counter: Counter) -> None:
        self.counter = counter
        super().__init__()

    def request(self, *args: Any, **kwargs: Any) -> Response:
        self.counter.inc()
        return super().request(*args, **kwargs)
