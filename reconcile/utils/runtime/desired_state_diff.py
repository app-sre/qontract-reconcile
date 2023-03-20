import logging
import multiprocessing
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Iterable,
    Mapping,
    Optional,
)

from deepdiff import DeepHash
from jsonpath_ng.ext.parser import parse

from reconcile.change_owners.diff import (
    Diff,
    DiffType,
    extract_diffs,
)
from reconcile.utils.jsonpath import apply_constraint_to_path
from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    ShardedRunProposal,
)


@dataclass
class DesiredStateDiff:
    """
    Describes the diff between two desired states and potentially the affected
    shards.
    """

    previous_desired_state: Mapping[str, Any]
    """
    The desired state of an integration before the change.
    """
    current_desired_state: Mapping[str, Any]
    """
    The desired state of an integration after the change.
    """
    diff_found: bool
    """
    Whether there are any differences between the two states
    """
    affected_shards: set[str]
    """
    The shards affected by the change.
    """

    def can_exit_early(self) -> bool:
        return not self.diff_found


def find_changed_shards(
    diffs: Iterable[Diff],
    previous_desired_state: Mapping[str, Any],
    current_desired_state: Mapping[str, Any],
    sharding_config: DesiredStateShardConfig,
) -> set[str]:
    """
    Finds the affected desired state shards introduced by a set of diffs. The
    affected shards are determined by the shard path selectors from the
    provided `DesiredStateShardConfig`.
    """
    affected_shards = set()
    for d in diffs:
        for shard_path_spec in sharding_config.shard_path_selectors:
            shard_path = apply_constraint_to_path(parse(shard_path_spec), d.path)
            if shard_path:
                if d.diff_type in {DiffType.CHANGED, d.diff_type.REMOVED}:
                    affected_shards.update(
                        {
                            shard.value
                            for shard in shard_path.find(previous_desired_state)
                        }
                    )
                if d.diff_type in {DiffType.CHANGED, d.diff_type.ADDED}:
                    affected_shards.update(
                        {
                            shard.value
                            for shard in shard_path.find(current_desired_state)
                        }
                    )
    return affected_shards


EXTRACT_TASK_RESULT_KEY_DIFFS = "diffs"
EXTRACT_TASK_RESULT_KEY_ERROR = "error"


def _extract_diffs_task(
    extraction_function: Callable[
        [Mapping[str, Any], Mapping[str, Any]], Iterable[Diff]
    ],
    previous_desired_state: Mapping[str, Any],
    current_desired_state: Mapping[str, Any],
    return_value: dict,
) -> None:
    """
    A multiprocessing task that extracts diffs from two desired states
    and stores them in a return value dictionary.
    """
    try:
        diffs = extraction_function(previous_desired_state, current_desired_state)
        return_value[EXTRACT_TASK_RESULT_KEY_DIFFS] = diffs
    except BaseException as e:
        return_value[EXTRACT_TASK_RESULT_KEY_ERROR] = e


class DiffDetectionTimeout(Exception):
    """
    Raised when the fine grained diff detection takes too long.
    """


class DiffDetectionFailure(Exception):
    """
    Raised when the fine grained diff detection fails.
    """


def extract_diffs_with_timeout(
    extraction_function: Callable[
        [Mapping[str, Any], Mapping[str, Any]], Iterable[Diff]
    ],
    previous_desired_state: Mapping[str, Any],
    current_desired_state: Mapping[str, Any],
    timeout_seconds: int,
) -> list[Diff]:
    """
    Extracts diffs from two desired states using a dedicated extraction function.
    If the timeout is reached, a `DiffDetectionTimeout` exception is raised.

    The diff extraction is performed in a separate process for the sole purpose
    to be able to enforce a timeout. This is necessary because the diff extraction
    can take a long time for large desired states. Stoping the process is reasonable
    for multiple reasons:
        * the process can potentially take minutes to complete. that would deminish
          the value derived from the detected diffs (e.g. sharded runs)
        * the process can potentially take a lot of memory the longer it runs,
          which would put more pressure on the system executing the process, e.g.
          Jenkins
        * experience has shown that the diff extraction process yields the most
          valueable results when it is fast. if it takes too long, the results
          yield contain too many diffs to be meaningful for followup processing
    """
    m = multiprocessing.Manager()
    result_value = m.dict()

    process = multiprocessing.Process(
        target=_extract_diffs_task,
        args=(
            extraction_function,
            previous_desired_state,
            current_desired_state,
            result_value,
        ),
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        logging.info(
            f"timeout {timeout_seconds}s reached to find fine grained diffs. "
            "no shard detection or sharded runs will be performed."
        )
        process.terminate()
        process.join()
        raise DiffDetectionTimeout()

    if EXTRACT_TASK_RESULT_KEY_DIFFS in result_value:
        return result_value[EXTRACT_TASK_RESULT_KEY_DIFFS]

    original_error = result_value.get(EXTRACT_TASK_RESULT_KEY_ERROR)
    if original_error:
        raise DiffDetectionFailure() from original_error

    # not every error situation of the diff extraction process
    # will result in an exception. the lack of a result is an error
    # indicator as well. in those cases, we raise at least
    # a generic exception to indicate that something went wrong
    raise DiffDetectionFailure("unknown error during fine grained diff detection")


def build_desired_state_diff(
    sharding_config: Optional[DesiredStateShardConfig],
    previous_desired_state: Mapping[str, Any],
    current_desired_state: Mapping[str, Any],
) -> DesiredStateDiff:
    """
    Builds a `DesiredStateDiff` object based on the provided desired states.
    If sharding config is provided, the diff will also contain the affected
    shards introduced by the change between the two desired states.
    """
    # is there even a difference?
    previous_hash = DeepHash(previous_desired_state)
    current_hash = DeepHash(current_desired_state)
    desired_state_diff_found = previous_hash.get(
        previous_desired_state
    ) != current_hash.get(current_desired_state)

    shards = set()
    exract_diff_timeout_seconds = 10
    try:
        if desired_state_diff_found and sharding_config:
            # detect shards based on fine grained diffs
            diffs = extract_diffs_with_timeout(
                extraction_function=extract_diffs,
                previous_desired_state=previous_desired_state,
                current_desired_state=current_desired_state,
                timeout_seconds=exract_diff_timeout_seconds,
            )
            changed_shards = find_changed_shards(
                diffs=diffs,
                previous_desired_state=previous_desired_state,
                current_desired_state=current_desired_state,
                sharding_config=sharding_config,
            )
            if changed_shards:
                # let the integration decide if the sharding proposal is fine
                if sharding_config.sharded_run_review(
                    ShardedRunProposal(proposed_shards=changed_shards)
                ):
                    shards = changed_shards
    except DiffDetectionTimeout:
        logging.warning(
            f"unable to extract fine grained diffs for shard extraction "
            f"within {exract_diff_timeout_seconds} seconds. continue without sharding"
        )
    except DiffDetectionFailure as e:
        logging.warning(
            f"unable to extract fine grained diffs for shard extraction: {e}"
        )

    return DesiredStateDiff(
        previous_desired_state=previous_desired_state,
        current_desired_state=current_desired_state,
        diff_found=desired_state_diff_found,
        affected_shards=shards,
    )
