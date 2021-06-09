import os
import subprocess

import pytest


def run_make(sub_command):
    cmd = ['make', sub_command]
    return subprocess.run(cmd, check=True)


def has_uncommited_changes():
    cmd = ['git', 'diff']
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=True)
    if result.stdout:
        return True
    return False


class TestMake:
    @staticmethod
    @pytest.mark.skipif(
        not os.environ.get("HUDSON_HOME"),
        reason="This test is only for CI environments",
    )
    def test_make_generate():
        assert not has_uncommited_changes(), ('No uncommited changes must '
                                              'exists')

        result = run_make('generate')
        # Just to make sure the command does not fail
        assert not result.returncode

        assert not has_uncommited_changes(), ('No uncommited changes must '
                                              'exists after "make generate"')
