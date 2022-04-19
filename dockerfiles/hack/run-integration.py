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
from reconcile.utils.metrics import (
  run_time, run_status, extra_labels, execution_counter
)


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


def _parse_dry_run_flag(dry_run: str) -> Optional[str]:
    dry_run_options = ['--dry-run', '--no-dry-run']
    if dry_run is not None and dry_run not in dry_run_options:
        msg = (
          f'Invalid DRY_RUN option given: "{dry_run}".'
          f'Only the following options are allowed: {dry_run_options}'
        )
        logging.error(msg)
        raise ValueError(msg)
    return dry_run if dry_run else None


def build_entry_point_args(command: click.Command, config: str,
                           dry_run: Optional[str], integration_name: str,
                           extra_args: Optional[str]) -> list[str]:
    args = ['--config', config]
    if dry_run_flag := _parse_dry_run_flag(dry_run):
        args.append(dry_run_flag)

    # if the integration_name is a known sub command,
    # we add it right before the extra_args
    if integration_name and isinstance(command, click.MultiCommand) and \
            command.get_command(None, integration_name):  # type: ignore
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
    entry_point: Optional[metadata.EntryPoint] = \
        console_script_entry_points.get(command_name, None)
    if entry_point:
        return entry_point.load()
    else:
        raise ValueError(
            f"Command {command_name} unknown."
            f"Have a look at setup.py for valid entry points.")


def main():
    """
    This entry point script expects certain env variables
    * COMMAND_NAME (optional, defaults to qontract-reconcile)
      an entry point as defined in setup.py must be a click.Command
    * INTEGRATION_NAME
      used as name for the subcommand for command if present as a subcommand
      on the click command
    * INTEGRATION_EXTRA_ARGS (optional)
      space separated list of arguments that will be passed to the command
      or subcommand
    * CONFIG
      path to the config toml file
    * LOG_FILE
      path for the logfile to write to
    * DRY_RUN (optional)
      this is not a boolean but must contain the actual dry-run flag value,
      so --dry-run or --no-dry-run
    * RUN_ONCE (optional)
      if 'true', execute the integration once and exit
      otherwise run the integration in a loop controlled by SLEEP_DURATION_SECS
      and SLEEP_ON_ERROR
    * SLEEP_DURATION_SECS (default 600)
      amount of seconds to sleep between successful integration runs
    * SLEEP_ON_ERROR (default 10)
      amount of seconds to sleep before another integration run is started

    Based on those variables, the following command will be executed
      $COMMAND --config $CONFIG $DRY_RUN $INTEGRATION_NAME \
        $INTEGRATION_EXTRA_ARGS
    """

    start_http_server(9090)

    command = build_entry_point_func(COMMAND_NAME)
    while True:
        args = build_entry_point_args(command, CONFIG, DRY_RUN,
                                      INTEGRATION_NAME, INTEGRATION_EXTRA_ARGS)
        sleep = SLEEP_DURATION_SECS
        start_time = time.monotonic()
        # Running the integration via Click, so we don't have to replicate
        # the CLI logic here
        execution_counter.labels(
            integration=INTEGRATION_NAME,
            shards=SHARDS,
            shard_id=SHARD_ID,
            **extra_labels
        ).inc()
        try:
            with command.make_context(info_name=COMMAND_NAME, args=args) \
              as ctx:
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
        except Exception:
            sleep = SLEEP_ON_ERROR
            LOG.exception(f"Error running {COMMAND_NAME}")
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


if __name__ == "__main__":
    main()
