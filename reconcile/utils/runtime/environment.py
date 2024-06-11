import logging
import os
import sys

from reconcile.utils import (
    config,
    gql,
)

QONTRACT_CONFIG = "QONTRACT_CONFIG"
QONTRACT_LOG_LEVEL = "QONTRACT_LOG_LEVEL"

LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

DRY_RUN_MAP = {
    "--dry-run": True,
    "--no-dry-run": False,
}


def log_fmt(dry_run: bool | None = None, dry_run_option: str | None = None) -> str:
    if dry_run and dry_run_option:
        raise ValueError("Please set either dry_run or dry_run_option.")

    if dry_run_option:
        if dry_run_option not in DRY_RUN_MAP:
            raise ValueError(
                f'Invalid dry_run_option "{dry_run_option}". '
                f"Only the following options are allowed: {list(DRY_RUN_MAP.keys())}."
            )

        dry_run = DRY_RUN_MAP[dry_run_option]

    log_fmt = (
        "[%(asctime)s] [%(levelname)s] [DRY-RUN] "
        if dry_run
        else "[%(asctime)s] [%(levelname)s] "
    )

    log_fmt += "[%(filename)s:%(funcName)s:%(lineno)d] - %(message)s"

    return log_fmt


def init_env(
    log_level: str | None = None,
    config_file: str | None = None,
    dry_run: bool | None = None,
    print_gql_url: bool = True,
) -> None:
    # store env configs in environment variables. this way child processes
    # will inherit them and a compatible environment can be setup in a child
    # process easily by running `init_env()` with no parameters.
    if log_level:
        os.environ[QONTRACT_LOG_LEVEL] = log_level
    if config_file:
        os.environ[QONTRACT_CONFIG] = config_file

    # init loglevel
    logging.basicConfig(
        format=log_fmt(dry_run=dry_run),
        datefmt=LOG_DATEFMT,
        level=getattr(logging, os.environ.get(QONTRACT_LOG_LEVEL, "INFO")),
    )

    # init basic config
    config_file = os.environ.get(QONTRACT_CONFIG)
    if not config_file:
        logging.fatal("no config file for qontract-reconcile specified")
        sys.exit(1)
    config.init_from_toml(config_file)

    # init basic gql connection
    gql.init_from_config(print_url=print_gql_url)
