import logging
from contextlib import contextmanager

DEFAULT_TOGGLE_LEVEL = logging.ERROR


@contextmanager
def toggle_logger(log_level: int = DEFAULT_TOGGLE_LEVEL):
    logger = logging.getLogger()
    default_level = logger.level
    try:
        yield logger.setLevel(log_level)  # type: ignore[func-returns-value]
    finally:
        logger.setLevel(default_level)
