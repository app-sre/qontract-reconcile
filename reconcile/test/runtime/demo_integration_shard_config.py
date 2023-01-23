from reconcile.utils.runtime.integration import DesiredStateShardConfig

QONTRACT_INTEGRATION = "demo-integration-sharded"
SHARD_ARG_NAME = "shard"


def run(dry_run: bool, some_arg: int, shard: str) -> None:
    pass


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name=SHARD_ARG_NAME,
        shard_path_selectors={"shard[*].name"},
        sharded_run_review=lambda _: True,
    )
