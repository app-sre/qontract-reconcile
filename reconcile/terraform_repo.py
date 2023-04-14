from typing import Callable, Optional
from reconcile.utils.defer import defer
from reconcile.utils.semver_helper import make_semver

import logging

from reconcile.utils.state import init_state

QONTRACT_INTEGRATION = "terraform-repo"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 1, 0)

@defer
def run(
    dry_run: bool,
    print_to_file: Optional[str] = None,
    defer: Optional[Callable] = None,
    ) -> None:

    state = init_state(integration=QONTRACT_INTEGRATION)
    defer(state.cleanup)

    # get the desired state by querying GQL for repos
    # gotta use qenerate for this to have nicely typed defs

    # get the current state by checking the State class with AWS S3

    # determine an action plan and write it out with YAML using yaml.dump
