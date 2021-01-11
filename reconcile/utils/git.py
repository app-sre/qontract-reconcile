import os

from subprocess import Popen


class GitError(Exception):
    pass


def clone(repo_url, wd):
    DEVNULL = open(os.devnull, 'w')
    proc = Popen(['git', 'clone', repo_url, wd],
                 stdout=DEVNULL, stderr=DEVNULL)
    proc.communicate()
    if proc.returncode != 0:
        raise GitError('git clone failed: {}'.format(repo_url))


def checkout(commit, wd):
    DEVNULL = open(os.devnull, 'w')
    proc = Popen(['git', 'checkout', commit],
                 cwd=wd, stdout=DEVNULL, stderr=DEVNULL)
    proc.communicate()
    if proc.returncode != 0:
        raise GitError('git checkout failed: {}'.format(commit))
