import os

from sretoolbox.container import Image
from sretoolbox.container import Skopeo

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


class InstrumentedCache:
    def __init__(self, integration_name, shards, shard_id):
        self.integraton_name = integration_name
        self.shards = shards
        self.shard_id = shard_id

        self._hits = metrics.cache_hits.labels(
            integration=integration_name, shards=shards, shard_id=shard_id
        )
        self._misses = metrics.cache_misses.labels(
            integration=integration_name, shards=shards, shard_id=shard_id
        )
        self._size = metrics.cache_size.labels(
            integration=integration_name, shards=shards, shard_id=shard_id
        )

        self._cache = {}

    def __getitem__(self, item):
        if item in self._cache:
            self._hits.inc()
        else:
            self._misses.inc()
        return self._cache[item]

    def __setitem__(self, key, value):
        self._cache[key] = value
        self._size.inc()

    def __delitem__(self, key):
        del self._cache[key]
        self._size.dec(1)


class InstrumentedSkopeo(Skopeo):
    def copy(self, *args, **kwargs):
        # pylint: disable=signature-differs
        metrics.copy_count.labels(
            integration=INTEGRATION_NAME, shard=SHARDS, shard_id=SHARD_ID
        ).inc()
        return super().copy(*args, **kwargs)
