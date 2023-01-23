from dataclasses import dataclass
from typing import (
    Any,
)

from deepdiff import DeepHash


@dataclass
class DesiredStateDiff:

    previous_desired_state: Any
    current_desired_state: Any
    diff_found: bool

    def can_exit_early(self) -> bool:
        return not self.diff_found


def build_desired_state_diff(
    previous_desired_state: dict[str, Any],
    current_desired_state: dict[str, Any],
) -> DesiredStateDiff:
    # is there a difference?
    previous_hash = DeepHash(previous_desired_state)
    current_hash = DeepHash(current_desired_state)
    desired_state_diff_found = previous_hash.get(
        previous_desired_state
    ) != current_hash.get(current_desired_state)
    return DesiredStateDiff(
        previous_desired_state=previous_desired_state,
        current_desired_state=current_desired_state,
        diff_found=desired_state_diff_found,
    )
