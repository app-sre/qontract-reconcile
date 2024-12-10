#!/usr/bin/env python3

import logging
import os
import sys
import time
from collections.abc import Callable
from importlib import metadata

import click
from prometheus_client import (
    push_to_gateway,
    start_http_server,
)
from prometheus_client.exposition import basic_auth_handler

from reconcile.status import ExitCodes
from reconcile.utils.metrics import (
    execution_counter,
    pushgateway_registry,
    pushgateway_run_status,
    pushgateway_run_time,
    run_status,
    run_time,
)
from reconcile.utils.runtime.environment import (
    LOG_DATEFMT,
    log_fmt,
)

SHARDS = int(os.environ.get("SHARDS", "1"))
SHARD_ID = int(os.environ.get("SHARD_ID", "0"))
SHARD_ID_LABEL = os.environ.get("SHARD_KEY", f"{SHARD_ID}-{SHARDS}")
PREFIX_LOG_LEVEL = os.environ.get("PREFIX_LOG_LEVEL", "false")

INTEGRATION_NAME = os.environ.get("INTEGRATION_NAME")
COMMAND_NAME = os.environ.get("COMMAND_NAME", "qontract-reconcile")

RUN_ONCE = os.environ.get("RUN_ONCE")
DRY_RUN = (
    os.environ.get("MANAGER_DRY_RUN")
    if INTEGRATION_NAME == "integrations-manager"
    else os.environ.get("DRY_RUN")
)
INTEGRATION_EXTRA_ARGS = os.environ.get("INTEGRATION_EXTRA_ARGS")
CONFIG = os.environ.get("CONFIG", "/config/config.toml")
PROMETHEUS_PORT = int(os.environ.get("PROMETHEUS_PORT", "9090"))

LOG_FILE = os.environ.get("LOG_FILE")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
SLEEP_DURATION_SECS = int(os.environ.get("SLEEP_DURATION_SECS", "600"))
SLEEP_ON_ERROR = int(os.environ.get("SLEEP_ON_ERROR", "10"))

PUSHGATEWAY_ENABLED = bool(os.environ.get("PUSHGATEWAY_ENABLED"))

LOG = logging.getLogger(__name__)

# Messages to stdout
STREAM_HANDLER = logging.StreamHandler(sys.stdout)
STREAM_HANDLER.setFormatter(
    logging.Formatter(fmt=log_fmt(dry_run_option=DRY_RUN), datefmt=LOG_DATEFMT)
)
HANDLERS = [STREAM_HANDLER]

# Messages to the log file
if LOG_FILE is not None:
    FILE_HANDLER = logging.FileHandler(LOG_FILE)
    logFileFormat = "%(message)s"
    if PREFIX_LOG_LEVEL == "true":
        logFileFormat = "[%(levelname)s] %(message)s"
    FILE_HANDLER.setFormatter(logging.Formatter(fmt=logFileFormat))
    HANDLERS.append(FILE_HANDLER)  # type: ignore

# Setting up the root logger
logging.basicConfig(level=LOG_LEVEL, handlers=HANDLERS)


class PushgatewayBadConfigError(Exception):
    pass


def _parse_dry_run_flag(dry_run: str | None) -> str | None:
    dry_run_options = ["--dry-run", "--no-dry-run"]
    if dry_run is not None and dry_run not in dry_run_options:
        msg = (
            f'Invalid DRY_RUN option given: "{dry_run}".'
            f"Only the following options are allowed: {dry_run_options}"
        )
        logging.error(msg)
        raise ValueError(msg)
    return dry_run or None


def build_entry_point_args(
    command: click.Command,
    config: str,
    dry_run: str | None,
    integration_name: str,
    extra_args: str | None,
) -> list[str]:
    args = ["--config", config]
    if dry_run_flag := _parse_dry_run_flag(dry_run):
        args.append(dry_run_flag)

    # if the integration_name is a known sub command,
    # we add it right before the extra_args
    if (
        integration_name
        and isinstance(command, click.MultiCommand)
        and command.get_command(None, integration_name)  # type: ignore
    ):
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
        ep.name: ep for ep in metadata.entry_points().select(group="console_scripts")
    }
    entry_point: metadata.EntryPoint | None = console_script_entry_points.get(
        command_name
    )
    if entry_point:
        return entry_point.load()
    raise ValueError(
        f"Command {command_name} unknown."
        f"Have a look at setup.py for valid entry points."
    )


def _get_pushgateway_env_vars() -> dict[str, str]:
    env = {}
    missing_vars = []
    for var in ["PUSHGATEWAY_USERNAME", "PUSHGATEWAY_PASSWORD", "PUSHGATEWAY_URL"]:
        value = os.environ.get(var)
        if not value:
            missing_vars.append(var)
            continue

        env[var] = value

    if missing_vars:
        missing_str = ", ".join(missing_vars)
        raise PushgatewayBadConfigError(
            f"Failed to check env variables to configure Pushgateway: {missing_str}"
        )

    return env


def _push_gateway_basic_auth_handler(
    url: str,
    method: str,
    timeout: float | None,
    headers: list[tuple[str, str]],
    data: bytes,
) -> Callable[[], None]:
    username = os.environ.get("PUSHGATEWAY_USERNAME")
    password = os.environ.get("PUSHGATEWAY_PASSWORD")

    # We should not get here, but this will make mypy happy
    if not username or not password:
        raise PushgatewayBadConfigError(
            "Failed to check env variables to configure Pushgateway."
        )

    return basic_auth_handler(url, method, timeout, headers, data, username, password)


def main() -> None:
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
    * LOG_LEVEL
      Log level (defaults to INFO)
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
    * PUSHGATEWAY_ENABLED (defaults to false)
      send metrics to a Prometheus Pushgateway after the run. In expects
      "PUSHGATEWAY_USERNAME", "PUSHGATEWAY_PASSWORD" and "PUSHGATEWAY_URL" to be defined.


    Based on those variables, the following command will be executed
      $COMMAND --config $CONFIG $DRY_RUN $INTEGRATION_NAME \
        $INTEGRATION_EXTRA_ARGS
    """
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(main.__doc__)
        sys.exit(0)

    if not INTEGRATION_NAME:
        raise ValueError("INTEGRATION_NAME env variable is required")

    start_http_server(int(PROMETHEUS_PORT))

    command = build_entry_point_func(COMMAND_NAME)
    while True:
        args = build_entry_point_args(
            command, CONFIG, DRY_RUN, INTEGRATION_NAME, INTEGRATION_EXTRA_ARGS
        )
        sleep = SLEEP_DURATION_SECS
        start_time = time.monotonic()
        # Running the integration via Click, so we don't have to replicate
        # the CLI logic here
        execution_counter.labels(
            integration=INTEGRATION_NAME, shards=SHARDS, shard_id=SHARD_ID_LABEL
        ).inc()
        try:
            with command.make_context(info_name=COMMAND_NAME, args=args) as ctx:  # type: ignore
                ctx.ensure_object(dict)
                command.invoke(ctx)
                return_code = 0
        # This is for when the integration explicitly
        # calls sys.exit(N)
        except SystemExit as exc_obj:
            return_code = int(exc_obj.code)  # type: ignore[arg-type]
        # We have to be generic since we don't know what can happen
        # in the integrations, but we want to continue the loop anyway
        except Exception:
            sleep = SLEEP_ON_ERROR
            LOG.exception(f"Error running {COMMAND_NAME}")
            return_code = ExitCodes.ERROR

        time_spent = time.monotonic() - start_time

        run_time.labels(
            integration=INTEGRATION_NAME, shards=SHARDS, shard_id=SHARD_ID_LABEL
        ).set(time_spent)
        run_status.labels(
            integration=INTEGRATION_NAME, shards=SHARDS, shard_id=SHARD_ID_LABEL
        ).set(return_code)

        if PUSHGATEWAY_ENABLED:
            try:
                env = _get_pushgateway_env_vars()
                pushgateway_run_time.labels(
                    integration=INTEGRATION_NAME, shards=SHARDS, shard_id=SHARD_ID_LABEL
                ).set(time_spent)
                pushgateway_run_status.labels(
                    integration=INTEGRATION_NAME, shards=SHARDS, shard_id=SHARD_ID_LABEL
                ).set(return_code)

                grouping_key = {
                    "integration": INTEGRATION_NAME,
                    "shards": SHARDS,
                    "shard_id": SHARD_ID_LABEL,
                }
                push_to_gateway(
                    gateway=env["PUSHGATEWAY_URL"],
                    job="qontract-reconcile",
                    registry=pushgateway_registry,
                    handler=_push_gateway_basic_auth_handler,
                    grouping_key=grouping_key,
                )
            except PushgatewayBadConfigError as err:
                LOG.exception(f"Error pushing to PushGateway: {err}")
                return_code = ExitCodes.ERROR

        if RUN_ONCE:
            sys.exit(return_code)

        time.sleep(int(sleep))


if __name__ == "__main__":
    main()
