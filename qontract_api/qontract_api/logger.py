"""Logging configuration for qontract-api."""

import logging
import sys

from qontract_api.config import settings


def setup_logging() -> logging.Logger:
    """Configure and return application logger."""
    logger = logging.getLogger("qontract_api")
    logger.setLevel(settings.LOG_LEVEL)

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.LOG_LEVEL)

    # Format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


logger = setup_logging()
