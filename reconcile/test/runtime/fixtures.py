from typing import (
    Any,
    Optional,
)

import pytest

from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    PydanticRunParams,
    QontractReconcileIntegration,
)


class SimpleTestIntegrationParams(PydanticRunParams):
    int_arg: int
    opt_str_arg: Optional[str] = None


class SimpleTestIntegration(QontractReconcileIntegration[SimpleTestIntegrationParams]):
    def __init__(self):
        self.desired_state_data = {}

    @property
    def name(self) -> str:
        return "test-integration"

    def get_early_exit_desired_state(
        self, params: SimpleTestIntegrationParams
    ) -> dict[str, Any]:
        return self.desired_state_data

    def get_desired_state_shard_config(self) -> Optional[DesiredStateShardConfig]:
        return None

    def run(self, dry_run: bool, params: SimpleTestIntegrationParams) -> None:
        pass


@pytest.fixture
def simple_test_integration() -> SimpleTestIntegration:
    return SimpleTestIntegration()


class ShardableTestIntegrationParams(PydanticRunParams):
    shard: Optional[str] = None


class ShardableTestIntegration(
    QontractReconcileIntegration[ShardableTestIntegrationParams]
):
    def __init__(self):
        self.desired_state_data = {}

    @property
    def name(self) -> str:
        return "shardable-test-integration"

    def get_early_exit_desired_state(
        self, params: ShardableTestIntegrationParams
    ) -> dict[str, Any]:
        return self.desired_state_data

    def get_desired_state_shard_config(self) -> Optional[DesiredStateShardConfig]:
        return DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"shards[*].shard"},
            sharded_run_review=lambda srp: True,
        )

    def run(self, dry_run: bool, params: ShardableTestIntegrationParams) -> None:
        pass


@pytest.fixture
def shardable_test_integration() -> ShardableTestIntegration:
    return ShardableTestIntegration()
