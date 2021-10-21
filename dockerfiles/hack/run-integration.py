#!/usr/bin/env python3

import logging
import os
import sys
import time
from typing import Optional

from prometheus_client import start_http_server
from importlib import metadata
import click

from reconcile.status import ExitCodes
from reconcile.cli import LOG_FMT, LOG_DATEFMT
from reconcile.utils.metrics import run_time
from reconcile.utils.metrics import run_status
from reconcile.utils.metrics import extra_labels


SHARDS = int(os.environ.get('SHARDS', 1))
SHARD_ID = int(os.environ.get('SHARD_ID', 0))

INTEGRATION_NAME = os.environ['INTEGRATION_NAME']
COMMAND_NAME = os.environ.get('COMMAND_NAME', 'qontract-reconcile')

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


def build_entry_point_args(command: click.Command, config: str,
                           dry_run: str, integration_name: str,
                           extra_args: str) -> list[str]:
    args = ['--config', config]
    if dry_run is not None:
        args.append(dry_run)

    # if the integration_name is a known sub command, we add it right before the extra_args
    if integration_name and isinstance(command, click.MultiCommand) and \
            command.get_command(None, integration_name):
        args.append(integration_name)

    if extra_args is not None:
        args.extend(extra_args.split())
    return args


def build_entry_point_func(command_name: str) -> click.Command:
    """
    Use the entry point information from setup.py to
    find the function to invoke for a command.
    """
    console_script_entry_points = {
        ep.name: ep
        for ep in metadata.entry_points()["console_scripts"]
    }
    entry_point: Optional[metadata.EntryPoint] = console_script_entry_points.get(command_name, None)
    if entry_point:
        return entry_point.load()
    else:
        raise ValueError(
            f"Command {command_name} unknown."
            f"Have a look at setup.py for valid entry points.")


if __name__ == "__main__":
    start_http_server(9090)

    command = build_entry_point_func(COMMAND_NAME)
    args = build_entry_point_args(command, CONFIG, DRY_RUN, INTEGRATION_NAME, INTEGRATION_EXTRA_ARGS)
    while True:
        sleep = SLEEP_DURATION_SECS
        start_time = time.monotonic()
        # Running the integration via Click, so we don't have to replicate
        # the CLI logic here
        try:
            with command.make_context(info_name=COMMAND_NAME, args=args) as ctx:
                ctx.ensure_object(dict)
                ctx.obj['extra_labels'] = extra_labels
                command.invoke(ctx)
                return_code = 0
        # This is for when the integration explicitly
        # calls sys.exit(N)
        except SystemExit as exc_obj:
            return_code = int(exc_obj.code)
        # We have to be generic since we don't know what can happen
        # in the integrations, but we want to continue the loop anyway
        except Exception as exc_obj:
            sleep = SLEEP_ON_ERROR
            LOG.exception(f"Error running {COMMAND_NAME}: %s", exc_obj)
            return_code = ExitCodes.ERROR

        time_spent = time.monotonic() - start_time

        run_time.labels(integration=INTEGRATION_NAME,
                        shards=SHARDS, shard_id=SHARD_ID,
                        **extra_labels).set(time_spent)
        run_status.labels(integration=INTEGRATION_NAME,
                          shards=SHARDS, shard_id=SHARD_ID,
                          **extra_labels).set(return_code)

        if RUN_ONCE:
            sys.exit(return_code)

        time.sleep(int(sleep))
