"""Tests for Slack usergroup dry-run isolation."""

import pytest

from reconcile.slack_usergroups_api import (
    FULL_VALIDATION_SHARD,
    SlackUsergroupsIntegration,
    SlackUsergroupsIntegrationParams,
)
from reconcile.utils.runtime.integration import ShardedRunProposal


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
