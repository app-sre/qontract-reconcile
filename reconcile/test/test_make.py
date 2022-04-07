import os

import pytest

from reconcile.utils.git import has_uncommited_changes
from reconcile.utils.make import generate


@pytest.mark.skipif(
    os.getuid() != 0,
    reason="This test is only for CI environments",
)
def test_make_generate():
    assert not has_uncommited_changes(), "No uncommited changes must " "exists"

    result = generate()
    # Just to make sure the command does not fail
    assert not result.returncode

    assert not has_uncommited_changes(), (
        "No uncommited changes must " 'exists after "make generate"'
    )
