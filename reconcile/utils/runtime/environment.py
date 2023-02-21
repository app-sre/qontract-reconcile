import logging
import os
import sys
from typing import Optional

from reconcile.utils import (
    config,
    gql,
)

QONTRACT_CONFIG = "QONTRACT_CONFIG"
QONTRACT_LOG_LEVEL = "QONTRACT_LOG_LEVEL"

LOG_FMT = (
    "[%(asctime)s] [%(levelname)s] "
    "[%(filename)s:%(funcName)s:%(lineno)d] - %(message)s"
)
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def init_env(
    log_level: Optional[str] = None,
    config_file: Optional[str] = None,
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
        format=LOG_FMT,
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
