import subprocess


def run_make(sub_command):
    cmd = ['make', sub_command]
    return subprocess.run(cmd)


def has_uncommited_changes():
    cmd = ['git', 'diff']
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    if result.stdout:
        return True
    return False


class TestMake:
    def test_make_generate(self):
        assert not has_uncommited_changes(), ('No uncommited changes must '
                                              'exists')

        result = run_make('generate')
        # Just to make sure the command does not fail
        assert not result.returncode

        assert not has_uncommited_changes(), ('No uncommited changes must '
                                              'exists after "make generate"')
