from typing import Any

QONTRACT_INTEGRATION = "demo-integration-early-exit"


def run(dry_run: bool, some_arg: int) -> None:
    pass


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    return {
        "args": args,
        "kwargs": kwargs,
    }
