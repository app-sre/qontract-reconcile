import os
import subprocess


class GitError(Exception):
    pass


def clone(repo_url, wd):
    cmd = ['git', 'clone', repo_url, wd]
    # pylint: disable=subprocess-run-check
    result = subprocess.run(cmd, cwd=wd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise GitError(f'git clone failed: {repo_url}')


def checkout(commit, wd):
    cmd = ['git', 'checkout', commit]
    # pylint: disable=subprocess-run-check
    result = subprocess.run(cmd, cwd=wd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise GitError(f'git checkout failed: {commit}')


def is_file_in_git_repo(file_path):
    real_path = os.path.realpath(file_path)
    dir_path = os.path.dirname(real_path)
    cmd = ['git', 'rev-parse', '--is-inside-work-tree']
    # pylint: disable=subprocess-run-check
    result = subprocess.run(cmd, cwd=dir_path,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    return result.returncode == 0
