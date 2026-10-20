from typing import Any

from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    PydanticRunParams,
    QontractReconcileApiIntegration,
    QontractReconcileIntegration,
)


class SimpleTestIntegrationParams(PydanticRunParams):
    int_arg: int
    opt_str_arg: str | None = None


class SimpleTestIntegration(QontractReconcileIntegration[SimpleTestIntegrationParams]):
    def __init__(self, params: SimpleTestIntegrationParams):
        super().__init__(params)
        self.desired_state_data: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "test-integration"

    def get_early_exit_desired_state(self) -> dict[str, Any]:
        return self.desired_state_data

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig | None:
        return None

    def run(self, dry_run: bool) -> None:
        print(self.params.int_arg)


class ShardableTestIntegrationParams(PydanticRunParams):
    shard: str | None = None


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

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig | None:
        return DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"shards[*].shard"},
            sharded_run_review=lambda srp: True,
        )

    def run(self, dry_run: bool) -> None:
        pass


class ShardableApiTestIntegrationParams(PydanticRunParams):
    shard: str | None = None


class ShardableApiTestIntegration(
    QontractReconcileApiIntegration[ShardableApiTestIntegrationParams]
):
    @property
    def name(self) -> str:
        return "shardable-api-test-integration"

    def get_early_exit_desired_state(self) -> dict[str, Any]:
        return self.desired_state_data

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"shards[*].shard"},
            sharded_run_review=lambda _: True,
        )

    async def async_run(self, dry_run: bool) -> None:
        pass


class ApiTestIntegration(QontractReconcileApiIntegration[SimpleTestIntegrationParams]):
    """API integration that deliberately does not opt into desired-state support."""

    @property
    def name(self) -> str:
        return "api-test-integration"

    async def async_run(self, dry_run: bool) -> None:
        pass
