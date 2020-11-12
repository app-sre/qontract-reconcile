from prometheus_client import Gauge
from prometheus_client import Counter
from prometheus_client import Histogram


run_time = Gauge(name='qontract_reconcile_last_run_seconds',
                 documentation='Last run duration in seconds',
                 labelnames=['integration', 'shards', 'shard_id'])

run_status = Counter(name='qontract_reconcile_run_status',
                     documentation='Status of the runs',
                     labelnames=['integration', 'status',
                                 'shards', 'shard_id'])

reconcile_time = Histogram(name='qontract_reconcile_function_'
                                'elapsed_seconds_since_bundle_commit',
                           documentation='Run time seconds for tracked '
                                         'functions',
                           labelnames=['name', 'integration'],
                           buckets=(10.0, 30.0, 60.0, 150.0, 300.0, 600.0,
                                    1200.0, 1800.0, float("inf")))
