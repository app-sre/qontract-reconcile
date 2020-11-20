#!/usr/bin/env python3

import logging
import os
import sys
import time

from prometheus_client import start_http_server
from prometheus_client import Gauge
from prometheus_client import Counter

from reconcile.status import ExitCodes
from reconcile.cli import integration


SHARDS = int(os.environ.get('SHARDS', 1))
SHARD_ID = int(os.environ.get('SHARD_ID', 0))

INTEGRATION_NAME = os.environ['INTEGRATION_NAME']

RUN_ONCE = os.environ.get('RUN_ONCE')
DRY_RUN = os.environ.get('DRY_RUN')
INTEGRATION_EXTRA_ARGS = os.environ.get('INTEGRATION_EXTRA_ARGS')

LOG_FILE = os.environ.get('LOG_FILE')
SLEEP_DURATION_SECS = os.environ.get('SLEEP_DURATION_SECS', 600)
SLEEP_ON_ERROR = os.environ.get('SLEEP_ON_ERROR', 10)

LOG = logging.getLogger(__name__)

# Messages to stdout
STREAM_HANDLER = logging.StreamHandler(sys.stdout)
STREAM_HANDLER.setFormatter(logging.Formatter(fmt='%(message)s'))
LOG.addHandler(STREAM_HANDLER)

# Messages to the log file
if LOG_FILE is not None:
    FILE_HANDLER = logging.FileHandler(LOG_FILE)
    FILE_HANDLER.setFormatter(logging.Formatter(fmt='%(message)s'))
    LOG.addHandler(FILE_HANDLER)

LOG.setLevel(logging.INFO)


def build_args():
    args = ['--config', '/config/config.toml']
    if DRY_RUN is not None:
        args.append(DRY_RUN)
    args.append(INTEGRATION_NAME)
    if INTEGRATION_EXTRA_ARGS is not None:
        args.extend(INTEGRATION_EXTRA_ARGS.split())
    return args


if __name__ == "__main__":
    start_http_server(9090)

    run_time = Gauge(name='qontract_reconcile_last_run_seconds',
                     documentation='Last run duration in seconds',
                     labelnames=['integration', 'shards', 'shard_id'])

    run_status = Counter(name='qontract_reconcile_run_status',
                         documentation='Status of the runs',
                         labelnames=['integration', 'status',
                                     'shards', 'shard_id'])

    while True:
        sleep = SLEEP_DURATION_SECS
        start_time = time.monotonic()
        # Running the integration via Click, so we don't have to replicate
        # the CLI logic here
        try:
            with integration.make_context(info_name='qontract-reconcile',
                                          args=build_args()) as ctx:
                integration.invoke(ctx)
                return_code = 0
        # This is for when the integration explicitly
        # calls sys.exit(N)
        except SystemExit as exc_obj:
            return_code = int(exc_obj.code)
        # We have to be generic since we don't know what can happen
        # in the integrations, but we want to continue the loop anyway
        except Exception as exc_obj:
            sleep = SLEEP_ON_ERROR
            LOG.error('Error running qontract-reconcile: %s', exc_obj)
            return_code = ExitCodes.ERROR

        time_spent = time.monotonic() - start_time

        run_time.labels(integration=INTEGRATION_NAME,
                        shards=SHARDS, shard_id=SHARD_ID).set(time_spent)
        run_status.labels(integration=INTEGRATION_NAME, status=return_code,
                          shards=SHARDS, shard_id=SHARD_ID).inc()

        if return_code == ExitCodes.DATA_CHANGED:
            continue

        if RUN_ONCE:
            sys.exit(return_code)

        time.sleep(int(sleep))
