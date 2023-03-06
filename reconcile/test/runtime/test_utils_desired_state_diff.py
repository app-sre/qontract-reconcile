from time import sleep
from typing import Any

import jsonpath_ng
import pytest
from pytest_mock.plugin import MockerFixture

from reconcile.change_owners.diff import (
    IDENTIFIER_FIELD_NAME,
    Diff,
    DiffType,
)
from reconcile.test.runtime.fixtures import (
    ShardableTestIntegration,
    SimpleTestIntegration,
)
from reconcile.utils.runtime import desired_state_diff
from reconcile.utils.runtime.desired_state_diff import (
    DiffDetectionFailure,
    DiffDetectionTimeout,
    build_desired_state_diff,
    extract_diffs_with_timeout,
)
from reconcile.utils.runtime.integration import DesiredStateShardConfig

pytest_plugins = [
    "reconcile.test.runtime.fixtures",
]

#
# build desired state diff
#


def test_desired_state_diff_building(simple_test_integration: SimpleTestIntegration):
    desired_state_diff = build_desired_state_diff(
        simple_test_integration.get_desired_state_shard_config(),
        previous_desired_state={"data": "old"},
        current_desired_state={"data": "new"},
    )
    assert desired_state_diff.affected_shards == set()
    assert not desired_state_diff.can_exit_early()


def test_desired_state_diff_building_no_diffs(
    simple_test_integration: SimpleTestIntegration,
):
    desired_state_diff = build_desired_state_diff(
        simple_test_integration.get_desired_state_shard_config(),
        previous_desired_state={"data": [{"name": "a"}, {"name": "b"}]},
        current_desired_state={"data": [{"name": "a"}, {"name": "b"}]},
    )
    assert desired_state_diff.affected_shards == set()
    assert desired_state_diff.can_exit_early()


def test_desired_state_diff_building_unshardable_integration(
    simple_test_integration: SimpleTestIntegration,
):
    desired_state_diff = build_desired_state_diff(
        simple_test_integration.get_desired_state_shard_config(),
        previous_desired_state={
            "shards": [
                {"shard": "a", "value": "old"},
                {"shard": "b", "value": "old"},
            ]
        },
        current_desired_state={
            "shards": [
                {"shard": "a", "value": "old"},
                {"shard": "b", "value": "new"},
            ]
        },
    )
    assert desired_state_diff.affected_shards == set()


def test_desired_state_diff_building_shardable_integration(
    shardable_test_integration: ShardableTestIntegration,
):
    desired_state_diff = build_desired_state_diff(
        shardable_test_integration.get_desired_state_shard_config(),
        previous_desired_state={
            "shards": [
                {"shard": "a", "value": "old"},
                {"shard": "b", "value": "old"},
            ]
        },
        current_desired_state={
            "shards": [
                {"shard": "a", "value": "old"},
                {"shard": "b", "value": "new"},
            ]
        },
    )
    assert desired_state_diff.affected_shards == {"b"}


def diff_extration_with_3_second_sleep(
    old_file_content: Any, new_file_content: Any
) -> list[Diff]:
    sleep(3)
    return [
        Diff(
            diff_type=DiffType.CHANGED,
            path=jsonpath_ng.parse("shards[1].value"),
            old="old",
            new="new",
        )
    ]


def diff_extration_with_endless_recursion(
    old_file_content: Any, new_file_content: Any
) -> list[Diff]:
    return diff_extration_with_endless_recursion(old_file_content, new_file_content)


def diff_extration_with_exception(
    old_file_content: Any, new_file_content: Any
) -> list[Diff]:
    raise Exception("something went wrong")


def test_desired_state_diff_building_time(
    mocker: MockerFixture, shardable_test_integration: ShardableTestIntegration
):
    extract_diffs_with_timeout_mock = mocker.patch.object(
        desired_state_diff, "extract_diffs_with_timeout"
    )
    extract_diffs_with_timeout_mock.side_effect = DiffDetectionTimeout()
    diff = build_desired_state_diff(
        shardable_test_integration.get_desired_state_shard_config(),
        previous_desired_state={
            "shards": [
                {"shard": "a", "value": "old"},
                {"shard": "b", "value": "old"},
            ]
        },
        current_desired_state={
            "shards": [
                {"shard": "a", "value": "old"},
                {"shard": "b", "value": "new"},
            ]
        },
    )
    assert diff.affected_shards == set()


#
# extract diffs
#


def test_extract_diffs_with_timeout():
    """
    test timeout behaviour of diff extraction
    """
    previous_desired_state = {
        "shards": [
            {"shard": "a", "value": "old"},
            {"shard": "b", "value": "old"},
        ]
    }
    current_desired_state = {
        "shards": [
            {"shard": "a", "value": "old"},
            {"shard": "b", "value": "new"},
        ]
    }

    # the timeout is lower than the extraction duration -> TIMEOUT
    with pytest.raises(DiffDetectionTimeout):
        extract_diffs_with_timeout(
            diff_extration_with_3_second_sleep,
            previous_desired_state=previous_desired_state,
            current_desired_state=current_desired_state,
            timeout_seconds=1,
        )

    # the timeout is higher than the extraction duration -> NO TIMEOUT
    diffs = extract_diffs_with_timeout(
        diff_extration_with_3_second_sleep,
        previous_desired_state=previous_desired_state,
        current_desired_state=current_desired_state,
        timeout_seconds=5,
    )
    assert diffs
    assert isinstance(diffs[0], Diff)


def test_extract_diffs_with_recursion_issue():
    """
    test if a max recursion issue is caught properly
    """
    with pytest.raises(DiffDetectionFailure):
        extract_diffs_with_timeout(
            diff_extration_with_endless_recursion,
            previous_desired_state={},
            current_desired_state={},
            timeout_seconds=100,
        )


def test_extract_diffs_with_exception():
    """
    test with exception
    """
    with pytest.raises(DiffDetectionFailure):
        extract_diffs_with_timeout(
            diff_extration_with_exception,
            previous_desired_state={},
            current_desired_state={},
            timeout_seconds=100,
        )


#
# find changed shards
#


def test_config_removed_from_shard():
    """
    when something is removed from a shard, that shard is affected
    """
    assert build_desired_state_diff(
        sharding_config=DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"data[*].shard"},
            sharded_run_review=lambda x: True,
        ),
        previous_desired_state={
            "data": [
                {"shard": "a", "value": "a", IDENTIFIER_FIELD_NAME: "a"},
                {"shard": "b", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
        current_desired_state={
            "data": [
                {"shard": "b", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
    ).affected_shards == {"a"}


def test_config_added_into_shard():
    """
    when something is added to a shard, that shard is affected
    """
    assert build_desired_state_diff(
        sharding_config=DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"data[*].shard"},
            sharded_run_review=lambda x: True,
        ),
        previous_desired_state={
            "data": [
                {"shard": "b", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
        current_desired_state={
            "data": [
                {"shard": "a", "value": "a", IDENTIFIER_FIELD_NAME: "a"},
                {"shard": "b", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
    ).affected_shards == {"a"}


def test_config_in_shard_changes():
    """
    when something in a shard changes, that chard is affected
    """
    assert build_desired_state_diff(
        sharding_config=DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"data[*].shard"},
            sharded_run_review=lambda x: True,
        ),
        previous_desired_state={
            "data": [
                {"shard": "a", "value": "a", IDENTIFIER_FIELD_NAME: "a"},
                {"shard": "b", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
        current_desired_state={
            "data": [
                {"shard": "a", "value": "a", IDENTIFIER_FIELD_NAME: "a"},
                {"shard": "b", "value": "c", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
    ).affected_shards == {"b"}


def test_config_moved_to_another_shard():
    """
    when something moves to another shard, both shards are affected
    """
    assert build_desired_state_diff(
        sharding_config=DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"data[*].shard"},
            sharded_run_review=lambda x: True,
        ),
        previous_desired_state={
            "data": [
                {"shard": "a", "value": "a", IDENTIFIER_FIELD_NAME: "a"},
                {"shard": "b", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
        current_desired_state={
            "data": [
                {"shard": "a", "value": "a", IDENTIFIER_FIELD_NAME: "a"},
                {"shard": "c", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
    ).affected_shards == {
        "b",  # the old one
        "c",  # the new one
    }


def test_find_changed_shards_mixed_diff():
    assert build_desired_state_diff(
        sharding_config=DesiredStateShardConfig(
            shard_arg_name="shard",
            shard_path_selectors={"data[*].shard"},
            sharded_run_review=lambda x: True,
        ),
        previous_desired_state={
            "data": [
                {"shard": "a", "value": "a", IDENTIFIER_FIELD_NAME: "a"},
                {"shard": "b", "value": "b", IDENTIFIER_FIELD_NAME: "b"},
            ]
        },
        current_desired_state={
            "data": [
                {"shard": "b", "value": "c", IDENTIFIER_FIELD_NAME: "b"},
                {"shard": "c", "value": "d", IDENTIFIER_FIELD_NAME: "c"},
            ]
        },
    ).affected_shards == {
        "a",  # the deleted one
        "b",  # the changed one
        "c",  # the adde one
    }


def test_find_changed_shards_no_diff():
    assert (
        build_desired_state_diff(
            sharding_config=DesiredStateShardConfig(
                shard_arg_name="shard",
                shard_path_selectors={"data[*].shard"},
                sharded_run_review=lambda x: True,
            ),
            previous_desired_state={
                "data": [
                    {"shard": "a", "value": "a"},
                    {"shard": "b", "value": "b"},
                ]
            },
            current_desired_state={
                "data": [
                    {"shard": "a", "value": "a"},
                    {"shard": "b", "value": "b"},
                ]
            },
        ).affected_shards
        == set()
    )
