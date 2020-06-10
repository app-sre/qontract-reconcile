#!/usr/bin/env python3

import logging
import os
import subprocess
import sys
import time

from prometheus_client import start_http_server
from prometheus_client import Gauge
from prometheus_client import Counter

from reconcile.status import State


SHARDS = int(os.environ.get('SHARDS', 1))
SHARD_ID = int(os.environ.get('SHARD_ID', 0))

INTEGRATION_NAME = os.environ['INTEGRATION_NAME']

RUN_ONCE = os.environ.get('RUN_ONCE')
DRY_RUN = os.environ.get('DRY_RUN')
INTEGRATION_EXTRA_ARGS = os.environ.get('INTEGRATION_EXTRA_ARGS')

LOG_FILE = os.environ.get('LOG_FILE')
SLEEP_DURATION_SECS = os.environ.get('SLEEP_DURATION_SECS', 600)

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


def run_cmd():
    cmd = ['qontract-reconcile', '--config', '/config/config.toml']

    if DRY_RUN is not None:
        cmd.append(DRY_RUN)

    cmd.append(INTEGRATION_NAME)

    if INTEGRATION_EXTRA_ARGS is not None:
        cmd.extend(INTEGRATION_EXTRA_ARGS.split())

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)

    # Draining the subprocess STDOUT to the logger as the
    # subprocess is executed
    while True:
        output = process.stdout.readline().decode()
        # Print all the lines while they are not empty
        if output:
            LOG.info(output.strip())
            continue
        # With an empty line, check if the process is still running
        if process.poll() is not None:
            return process.poll()


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
        start_time = time.monotonic()
        return_code = run_cmd()
        time_spent = time.monotonic() - start_time

        if RUN_ONCE:
            sys.exit(return_code)

        run_time.labels(integration=INTEGRATION_NAME,
                        shards=SHARDS, shard_id=SHARD_ID).set(time_spent)
        run_status.labels(integration=INTEGRATION_NAME, status=return_code,
                          shards=SHARDS, shard_id=SHARD_ID).inc()

        if return_code == State.DATA_CHANGED:
            continue

        if return_code == State.ERROR:
            continue

        time.sleep(int(SLEEP_DURATION_SECS))
