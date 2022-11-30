import os

from sretoolbox.container import (
    Image,
    Skopeo,
)

from reconcile.utils import metrics

# TODO: move these to a shared, constants module

INTEGRATION_NAME = os.environ.get("INTEGRATION_NAME", "")
SHARDS = os.environ.get("SHARDS", 1)
SHARD_ID = int(os.environ.get("SHARD_ID", 0))


class InstrumentedImage(Image):
    """Normal Image that exposes the count of reachouts to external
    registries.

    It helps us understand the performance of our caches and predict
    our mirroring-related costs.

    """

    def _get_manifest(self):
        metrics.registry_reachouts.labels(
            integration=INTEGRATION_NAME,
            shard=SHARDS,
            shard_id=SHARD_ID,
            registry=self.registry,
        ).inc()
        super()._get_manifest()


class InstrumentedSkopeo(Skopeo):
    def copy(self, *args, **kwargs):
        # pylint: disable=signature-differs
        metrics.copy_count.labels(
            integration=INTEGRATION_NAME, shard=SHARDS, shard_id=SHARD_ID
        ).inc()
        return super().copy(*args, **kwargs)
