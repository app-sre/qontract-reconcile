import importlib

from unittest.mock import create_autospec, patch

from reconcile.utils import sharding

VALUE="saas-qontract-reconcile"

class TestSharding:
    def test_is_in_shard_single_shard(self, monkeypatch):
        monkeypatch.setenv('SHARDS', "1")
        monkeypatch.setenv('SHARD_ID', "0")
        # SHARDS and SHARD_ID are defined as global variables.
        # To get tests to pick up new environment variables,
        # reloading is required after each call to monkeypatch.setenv()
        importlib.reload(sharding)
        
        assert sharding.is_in_shard(VALUE) is True

    def test_is_in_shard_three_shards_pass(self, monkeypatch):
        monkeypatch.setenv('SHARDS', "3")
        monkeypatch.setenv('SHARD_ID', "1")
        importlib.reload(sharding)

        assert sharding.is_in_shard(VALUE) is True

    def test_is_in_shard_three_shards_fail(self, monkeypatch):
        monkeypatch.setenv('SHARDS', "3")
        monkeypatch.setenv('SHARD_ID', "2")
        importlib.reload(sharding)

        assert sharding.is_in_shard(VALUE) is False

    def test_is_in_shard_round_robin_single_shard(self, monkeypatch):
        monkeypatch.setenv('SHARDS', "1")
        monkeypatch.setenv('SHARD_ID', "0")
        importlib.reload(sharding)

        assert sharding.is_in_shard_round_robin(VALUE, 1) is True

    def test_is_in_shard_round_robin_three_shards_pass(self, monkeypatch):
        monkeypatch.setenv('SHARDS', "3")
        monkeypatch.setenv('SHARD_ID', "1")
        importlib.reload(sharding)

        assert sharding.is_in_shard_round_robin(VALUE, 1) is True

    def test_is_in_shard_round_robin_three_shards_fail(self, monkeypatch):
        monkeypatch.setenv('SHARDS', "3")
        monkeypatch.setenv('SHARD_ID', "1")
        importlib.reload(sharding)

        assert sharding.is_in_shard_round_robin(VALUE, 2) is False