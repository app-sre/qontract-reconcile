import os

from prometheus_client import Counter, Gauge

from sretoolbox.container import Image

# TODO: move these to a shared, constants module

INTEGRATION_NAME = os.environ.get('INTEGRATION_NAME', '')
SHARDS = os.environ.get('SHARDS', 1)
SHARD_ID = int(os.environ.get('SHARD_ID', 0))


class InstrumentedImage(Image):
    """Normal Image that exposes the count of reachouts to external
    registries.

    It helps us understand the performance of our caches and predict
    our mirroring-related costs.

    """
    _registry_reachouts = Counter(
        name='qontract_reconcile_registry_reachouts',
        documentation='Number GET requests on public image registries',
        labelnames=['integration', 'shard', 'shard_id'])

    def _get_manifest(self):
        self._registry_reachouts.labels(
            integration=INTEGRATION_NAME,
            shard=SHARDS,
            shard_id=SHARD_ID
        ).inc()
        super()._get_manifest()


class InstrumentedCache:
    _cache_hits = Counter(
        name='qontract_reconcile_cache_hits',
        documentation='Number of hits to this cache',
        labelnames=['integration', 'shards', 'shard_id']
    )

    _cache_misses = Counter(
        name='qontract_reconcile_cache_misses',
        documentation='Number of misses on this cache',
        labelnames=['integration', 'shards', 'shard_id']
    )

    _cache_size = Gauge(
        name='qontract_reconcile_cache_size',
        documentation='Size of the cache',
        labelnames=['integration', 'shards', 'shard_id']
    )

    def __init__(self, integration_name, shards, shard_id):
        self.integraton_name = integration_name
        self.shards = shards
        self.shard_id = shard_id

        self._hits = self._cache_hits.labels(
            integration=integration_name,
            shards=shards,
            shard_id=shard_id
        )
        self._misses = self._cache_misses.labels(
            integration=integration_name,
            shards=shards,
            shard_id=shard_id
        )
        self._size = self._cache_size.labels(
            integration=integration_name,
            shards=shards,
            shard_id=shard_id
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
