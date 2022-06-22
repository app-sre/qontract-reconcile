import logging
import pytest

from reconcile.utils.helpers import DEFAULT_TOGGLE_LEVEL, toggle_logger


@pytest.fixture
def default_level():
    default_level = logging.INFO
    assert default_level != DEFAULT_TOGGLE_LEVEL

    return default_level


@pytest.fixture
def custom_level(default_level):
    custom_level = logging.WARNING
    assert custom_level != default_level
    assert custom_level != DEFAULT_TOGGLE_LEVEL

    return custom_level


@pytest.fixture
def logger(default_level):
    logger = logging.getLogger()
    logger.level = default_level
    assert logger.level == default_level

    return logger


def test_toggle_logger_default_toggle_level(logger, default_level):
    with toggle_logger():
        assert logger.level == DEFAULT_TOGGLE_LEVEL

    assert logger.level == default_level


def test_toggle_logger_custom_level(logger, custom_level, default_level):
    with toggle_logger(custom_level):
        assert logger.level == custom_level

    assert logger.level == default_level


def test_toggle_logger_default_level(logger, default_level):
    with toggle_logger(default_level):
        assert logger.level == default_level

    assert logger.level == default_level
