from prometheus_client import Gauge
from prometheus_client import Histogram


extra_labels = {'key': None}
label_keys = list(extra_labels.keys())

run_time = Gauge(
     name='qontract_reconcile_last_run_seconds',
     documentation='Last run duration in seconds',
     labelnames=['integration', 'shards', 'shard_id'] + label_keys)

run_status = Gauge(
     name='qontract_reconcile_last_run_status',
     documentation='Last run status',
     labelnames=['integration', 'shards', 'shard_id'] + label_keys)

reconcile_time = Histogram(name='qontract_reconcile_function_'
                                'elapsed_seconds_since_bundle_commit',
                           documentation='Run time seconds for tracked '
                                         'functions',
                           labelnames=['name', 'integration'],
                           buckets=(60.0, 150.0, 300.0, 600.0, 1200.0, 1800.0,
                                    2400.0, 3000.0, float("inf")))
