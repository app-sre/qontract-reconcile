from prometheus_client import Gauge
from prometheus_client import Counter


run_time = Gauge(name='qontract_reconcile_last_run_seconds',
                 documentation='Last run duration in seconds',
                 labelnames=['integration', 'shards', 'shard_id'])

run_status = Counter(name='qontract_reconcile_run_status',
                     documentation='Status of the runs',
                     labelnames=['integration', 'status',
                                 'shards', 'shard_id'])
