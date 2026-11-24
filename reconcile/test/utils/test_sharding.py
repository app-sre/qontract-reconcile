from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest

from reconcile.utils import sharding

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest import MonkeyPatch

VALUE = "saas-qontract-reconcile"


@pytest.fixture(autouse=True)
def restore_sharding_globals() -> Generator[None]:
    # Reloading the module changes globals used by other tests in this worker.
    shards, shard_id = sharding.SHARDS, sharding.SHARD_ID
    yield
    sharding.SHARDS = shards
    sharding.SHARD_ID = shard_id


def test_is_in_shard_single_shard(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SHARDS", "1")
    monkeypatch.setenv("SHARD_ID", "0")
    # SHARDS and SHARD_ID are defined as global variables.
    # To get tests to pick up new environment variables,
    # reloading is required after each call to monkeypatch.setenv()
    importlib.reload(sharding)

    assert sharding.is_in_shard(VALUE) is True


def test_is_in_shard_three_shards_pass(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SHARDS", "3")
    monkeypatch.setenv("SHARD_ID", "1")
    importlib.reload(sharding)

    assert sharding.is_in_shard(VALUE) is True


def test_is_in_shard_three_shards_fail(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SHARDS", "3")
    monkeypatch.setenv("SHARD_ID", "2")
    importlib.reload(sharding)

    assert sharding.is_in_shard(VALUE) is False
