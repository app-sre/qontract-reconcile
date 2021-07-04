#!/usr/bin/env python3

import logging
import os
import sys
import time

from prometheus_client import start_http_server

from reconcile.status import ExitCodes
from reconcile.cli import integration, LOG_FMT, LOG_DATEFMT
from reconcile.utils.metrics import run_time
from reconcile.utils.metrics import run_status


SHARDS = int(os.environ.get('SHARDS', 1))
SHARD_ID = int(os.environ.get('SHARD_ID', 0))

INTEGRATION_NAME = os.environ['INTEGRATION_NAME']

RUN_ONCE = os.environ.get('RUN_ONCE')
DRY_RUN = os.environ.get('DRY_RUN')
INTEGRATION_EXTRA_ARGS = os.environ.get('INTEGRATION_EXTRA_ARGS')
CONFIG = os.environ.get('CONFIG', '/config/config.toml')

LOG_FILE = os.environ.get('LOG_FILE')
SLEEP_DURATION_SECS = os.environ.get('SLEEP_DURATION_SECS', 600)
SLEEP_ON_ERROR = os.environ.get('SLEEP_ON_ERROR', 10)

LOG = logging.getLogger(__name__)

# Messages to stdout
STREAM_HANDLER = logging.StreamHandler(sys.stdout)
STREAM_HANDLER.setFormatter(logging.Formatter(fmt=LOG_FMT,
                                              datefmt=LOG_DATEFMT))
HANDLERS = [STREAM_HANDLER]

# Messages to the log file
if LOG_FILE is not None:
    FILE_HANDLER = logging.FileHandler(LOG_FILE)
    FILE_HANDLER.setFormatter(logging.Formatter(fmt='%(message)s'))
    HANDLERS.append(FILE_HANDLER)

# Setting up the root logger
logging.basicConfig(level=logging.INFO,
                    handlers=HANDLERS)


def build_args():
    args = ['--config', CONFIG]
    if DRY_RUN is not None:
        args.append(DRY_RUN)
    args.append(INTEGRATION_NAME)
    if INTEGRATION_EXTRA_ARGS is not None:
        args.extend(INTEGRATION_EXTRA_ARGS.split())
    return args


if __name__ == "__main__":
    start_http_server(9090)

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
            LOG.exception('Error running qontract-reconcile: %s', exc_obj)
            return_code = ExitCodes.ERROR

        time_spent = time.monotonic() - start_time

        run_time.labels(integration=INTEGRATION_NAME,
                        shards=SHARDS, shard_id=SHARD_ID).set(time_spent)
        run_status.labels(integration=INTEGRATION_NAME,
                          shards=SHARDS, shard_id=SHARD_ID).set(return_code)

        if RUN_ONCE:
            sys.exit(return_code)

        time.sleep(int(sleep))
