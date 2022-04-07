import os
import subprocess

import pytest

from reconcile.utils.git import has_uncommited_changes


def run_make(sub_command):
    cmd = ["make", sub_command]
    return subprocess.run(cmd, check=True)



class TestMake:
    @staticmethod
    @pytest.mark.skipif(
        os.getuid() != 0,
        reason="This test is only for CI environments",
    )
    def test_make_generate():
        assert not has_uncommited_changes(), "No uncommited changes must " "exists"

        result = run_make("generate")
        # Just to make sure the command does not fail
        assert not result.returncode

        assert not has_uncommited_changes(), (
            "No uncommited changes must " 'exists after "make generate"'
        )
