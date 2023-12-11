QONTRACT_INTEGRATION = "demo-integration"

run_calls = []


def run(dry_run: bool, some_arg: int) -> None:
    run_calls.append({
        "some_arg": some_arg,
        "dry_run": dry_run,
    })
