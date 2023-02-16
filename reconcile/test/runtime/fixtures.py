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
    def __init__(self, params: SimpleTestIntegrationParams):
        super().__init__(params)
        self.desired_state_data: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "test-integration"

    def get_early_exit_desired_state(self) -> dict[str, Any]:
        return self.desired_state_data

    def get_desired_state_shard_config(self) -> Optional[DesiredStateShardConfig]:
        return None

    def run(self, dry_run: bool) -> None:
        print(self.params.int_arg)


@pytest.fixture
def simple_test_integration() -> SimpleTestIntegration:
    return SimpleTestIntegration(params=SimpleTestIntegrationParams(int_arg=1))


class ShardableTestIntegrationParams(PydanticRunParams):
    shard: Optional[str] = None


class ShardableTestIntegration(
    QontractReconcileIntegration[ShardableTestIntegrationParams]
):
    def __init__(self, params: ShardableTestIntegrationParams):
        super().__init__(params)
        self.desired_state_data: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "shardable-test-integration"

    def get_early_exit_desired_state(self) -> dict[str, Any]:
        return self.desired_state_data

    def get_desired_state_shard_config(self) -> Optional[DesiredStateShardConfig]:
        return DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"shards[*].shard"},
            sharded_run_review=lambda srp: True,
        )

    def run(self, dry_run: bool) -> None:
        pass


@pytest.fixture
def shardable_test_integration() -> ShardableTestIntegration:
    return ShardableTestIntegration(params=ShardableTestIntegrationParams())
