from prometheus_client import Gauge, Counter, Histogram


run_time = Gauge(
    name="qontract_reconcile_last_run_seconds",
    documentation="Last run duration in seconds",
    labelnames=["integration", "shards", "shard_id"],
)

run_status = Gauge(
    name="qontract_reconcile_last_run_status",
    documentation="Last run status",
    labelnames=["integration", "shards", "shard_id"],
)

execution_counter = Counter(
    name="qontract_reconcile_execution_counter",
    documentation="Counts started integration executions",
    labelnames=["integration", "shards", "shard_id"],
)

reconcile_time = Histogram(
    name="qontract_reconcile_function_" "elapsed_seconds_since_bundle_commit",
    documentation="Run time seconds for tracked " "functions",
    labelnames=["name", "integration"],
    buckets=(60.0, 150.0, 300.0, 600.0, 1200.0, 1800.0, 2400.0, 3000.0, float("inf")),
)

registry_reachouts = Counter(
    name="qontract_reconcile_registry_get_manifest_total",
    documentation="Number of GET requests on image registries",
    labelnames=["integration", "shard", "shard_id", "registry"],
)

cache_hits = Counter(
    name="qontract_reconcile_cache_hits_total",
    documentation="Number of hits to this cache",
    labelnames=["integration", "shards", "shard_id"],
)

cache_misses = Counter(
    name="qontract_reconcile_cache_misses_total",
    documentation="Number of misses on this cache",
    labelnames=["integration", "shards", "shard_id"],
)

cache_size = Gauge(
    name="qontract_reconcile_cache_cardinality",
    documentation="Number of keys in the cache",
    labelnames=["integration", "shards", "shard_id"],
)

copy_count = Counter(
    name="qontract_reconcile_skopeo_copy_total",
    documentation="Number of copy commands issued by Skopeo",
    labelnames=["integration", "shard", "shard_id"],
)
