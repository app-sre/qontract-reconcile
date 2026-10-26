"""Tests for Slack usergroup dry-run isolation."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from reconcile.slack_usergroups_api import (
    FULL_VALIDATION_SHARD,
    SlackUsergroupsIntegration,
    SlackUsergroupsIntegrationParams,
)
from reconcile.utils.runtime import runner
from reconcile.utils.runtime.desired_state_diff import build_desired_state_diff
from reconcile.utils.runtime.integration import ShardedRunProposal
from reconcile.utils.runtime.runner import (
    _integration_dry_run,
    _integration_wet_run,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


ACS_SHARD = '["red-hat","acs"]'
OTHER_SHARD = '["red-hat","unrelated"]'


def _desired_state(
    *,
    acs_schedule: str = "PTA0024",
    unrelated_description: str = "before",
    shared_users: tuple[str, ...] = ("alice",),
) -> dict[str, object]:
    return {
        "usergroups": [
            {
                "shard": ACS_SHARD,
                "permission": {
                    "description": "ACS",
                    "pagerduty": [{"scheduleID": acs_schedule}],
                },
            },
            {
                "shard": OTHER_SHARD,
                "permission": {"description": unrelated_description},
            },
        ],
        "shared_inputs": [
            {"shard": FULL_VALIDATION_SHARD, "users": list(shared_users)}
        ],
    }


@pytest.fixture
def integration() -> SlackUsergroupsIntegration:
    return SlackUsergroupsIntegration(
        SlackUsergroupsIntegrationParams(workspace_name=None, usergroup_name=None)
    )


def test_shard_identifier_round_trip(integration: SlackUsergroupsIntegration) -> None:
    assert integration._shard_filters(
        integration._shard_id("red hat", "acs:triage")
    ) == (
        "red hat",
        "acs:triage",
    )


@pytest.mark.parametrize("shard_id", ["not-json", '["workspace"]', '[1, "group"]'])
def test_invalid_shard_identifier_is_rejected(
    integration: SlackUsergroupsIntegration, shard_id: str
) -> None:
    with pytest.raises((TypeError, ValueError), match="Invalid Slack usergroup shard"):
        integration._shard_filters(shard_id)


def test_shared_input_change_forces_complete_validation(
    integration: SlackUsergroupsIntegration,
) -> None:
    config = integration.get_desired_state_shard_config()
    assert not config.sharded_run_review(ShardedRunProposal({FULL_VALIDATION_SHARD}))


def test_usergroup_only_change_is_eligible_for_isolated_validation(
    integration: SlackUsergroupsIntegration,
) -> None:
    assert integration.get_desired_state_shard_config().sharded_run_review(
        ShardedRunProposal({'["workspace","group"]'})
    )


def test_unchanged_state_exits_before_api_execution(
    integration: SlackUsergroupsIntegration,
    mocker: MockerFixture,
) -> None:
    desired_state = _desired_state()
    desired_state_diff = build_desired_state_diff(
        integration.get_desired_state_shard_config(),
        desired_state,
        desired_state,
    )
    async_run = mocker.patch.object(
        integration, "async_run", new_callable=mocker.AsyncMock
    )

    _integration_dry_run(integration, desired_state_diff)

    async_run.assert_not_awaited()


def test_unrelated_usergroup_change_does_not_run_acs_shard(
    integration: SlackUsergroupsIntegration,
    mocker: MockerFixture,
) -> None:
    """A stale ACS schedule is outside an unrelated usergroup's validation set."""
    desired_state_diff = build_desired_state_diff(
        integration.get_desired_state_shard_config(),
        _desired_state(),
        _desired_state(unrelated_description="after"),
    )
    async_run = mocker.patch.object(
        SlackUsergroupsIntegration, "async_run", autospec=True
    )
    mocker.patch.object(runner, "setup_qontract_api_client")
    mocker.patch.object(
        runner.qontract_api_client, "aclose", new_callable=mocker.AsyncMock
    )

    _integration_dry_run(integration, desired_state_diff)

    async_run.assert_awaited_once()
    assert async_run.await_args is not None
    selected_integration = async_run.await_args.args[0]
    assert selected_integration.params.shard_id == OTHER_SHARD


def test_acs_pagerduty_change_still_fails_acs_validation(
    integration: SlackUsergroupsIntegration,
    mocker: MockerFixture,
) -> None:
    """Changing ACS's PagerDuty reference cannot bypass its missing schedule."""
    desired_state_diff = build_desired_state_diff(
        integration.get_desired_state_shard_config(),
        _desired_state(),
        _desired_state(acs_schedule="MISSING-REPLACEMENT"),
    )

    async def fail_missing_schedule(
        selected: SlackUsergroupsIntegration, dry_run: bool
    ) -> None:
        await asyncio.sleep(0)
        assert dry_run
        assert selected.params.shard_id == ACS_SHARD
        raise RuntimeError("PagerDuty schedule PTA0024 was not found")

    mocker.patch.object(
        SlackUsergroupsIntegration,
        "async_run",
        autospec=True,
        side_effect=fail_missing_schedule,
    )
    mocker.patch.object(runner, "setup_qontract_api_client")
    mocker.patch.object(
        runner.qontract_api_client, "aclose", new_callable=mocker.AsyncMock
    )

    with pytest.raises(SystemExit, match="1"):
        _integration_dry_run(integration, desired_state_diff)


def test_shared_input_change_falls_back_to_full_dry_run(
    integration: SlackUsergroupsIntegration,
    mocker: MockerFixture,
) -> None:
    desired_state_diff = build_desired_state_diff(
        integration.get_desired_state_shard_config(),
        _desired_state(),
        _desired_state(shared_users=("alice", "bob")),
    )
    async_run = mocker.patch.object(
        integration, "async_run", new_callable=mocker.AsyncMock
    )
    mocker.patch.object(runner, "setup_qontract_api_client")
    mocker.patch.object(
        runner.qontract_api_client, "aclose", new_callable=mocker.AsyncMock
    )

    _integration_dry_run(integration, desired_state_diff)

    async_run.assert_awaited_once_with(True)
    assert integration.params.shard_id is None


def test_wet_run_is_always_complete(
    integration: SlackUsergroupsIntegration,
    mocker: MockerFixture,
) -> None:
    async_run = mocker.patch.object(
        integration, "async_run", new_callable=mocker.AsyncMock
    )
    mocker.patch.object(runner, "setup_qontract_api_client")
    mocker.patch.object(
        runner.qontract_api_client, "aclose", new_callable=mocker.AsyncMock
    )

    _integration_wet_run(integration)

    async_run.assert_awaited_once_with(False)
    assert integration.params.shard_id is None
