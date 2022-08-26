from dataclasses import dataclass
import logging
from types import ModuleType
from typing import Optional

from reconcile.utils import gql

from deepdiff import DeepDiff

EARLY_EXIT_DESIRED_STATE_FUNCTION = "early_exit_desired_state"


def integration_supports(func_container: ModuleType, func_name: str) -> bool:
    return func_name in dir(func_container)


@dataclass
class DesiredStateDiff:

    previous_desired_state: dict
    current_desired_state: dict
    diff: DeepDiff

    def can_exit_early(self) -> bool:
        return not self.diff


def find_desired_state_diff(
    int_name: str, compare_sha: str, func_container: ModuleType, *args, **kwargs
) -> Optional[DesiredStateDiff]:
    # does the integration support early exit?
    if not integration_supports(func_container, EARLY_EXIT_DESIRED_STATE_FUNCTION):
        logging.warning(
            f"{int_name} does not support early exit. it does not offer a "
            f"function called {EARLY_EXIT_DESIRED_STATE_FUNCTION}"
        )
        return None

    # get desired state from comparison bundle
    try:
        gql.init_from_config(
            sha=compare_sha,
            integration=int_name,
            validate_schemas=True,
            print_url=True,
        )
        previous_desired_state = func_container.early_exit_desired_state(
            *args, **kwargs
        )
    except Exception:
        logging.exception(
            f"Failed to fetch desired state for comparison bundle {compare_sha} failed"
        )
        return None

    # get desired state from current bundle
    try:
        gql.init_from_config(
            autodetect_sha=True,
            integration=int_name,
            validate_schemas=True,
            print_url=True,
        )
        current_desired_state = func_container.early_exit_desired_state(*args, **kwargs)
    except Exception:
        logging.exception("Failed to fetch desired state for current bundle failed")
        return None

    # compare
    diff = DeepDiff(previous_desired_state, current_desired_state, view="tree")
    return DesiredStateDiff(
        previous_desired_state=previous_desired_state,
        current_desired_state=current_desired_state,
        diff=diff,
    )
