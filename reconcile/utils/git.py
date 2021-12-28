import os

from subprocess import Popen


class GitError(Exception):
    pass


def clone(repo_url, wd):
    # pylint: disable=consider-using-with
    DEVNULL = open(os.devnull, 'w')
    proc = Popen(['git', 'clone', repo_url, wd],
                 stdout=DEVNULL, stderr=DEVNULL)
    proc.communicate()
    if proc.returncode != 0:
        raise GitError('git clone failed: {}'.format(repo_url))


def checkout(commit, wd):
    # pylint: disable=consider-using-with
    DEVNULL = open(os.devnull, 'w')
    proc = Popen(['git', 'checkout', commit],
                 cwd=wd, stdout=DEVNULL, stderr=DEVNULL)
    proc.communicate()
    if proc.returncode != 0:
        raise GitError('git checkout failed: {}'.format(commit))


def is_file_in_git_repo(file_path):
    real_path = os.path.realpath(file_path)
    dir_path = os.path.dirname(real_path)
    with open(os.devnull, 'w') as dev_null:
        proc = Popen(['git', 'git rev-parse', '--is-inside-work-tree'],
                    cwd=dir_path, stdout=dev_null, stderr=dev_null)
        proc.communicate()
    return proc.returncode == 0
