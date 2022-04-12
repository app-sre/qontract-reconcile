import os
import subprocess


class GitError(Exception):
    pass


def clone(repo_url, wd):
    # pylint: disable=subprocess-run-check
    cmd = ["git", "clone", repo_url, wd]
    result = subprocess.run(cmd, cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise GitError(f"git clone failed: {repo_url}")


def checkout(commit, wd):
    # pylint: disable=subprocess-run-check
    cmd = ["git", "checkout", commit]
    result = subprocess.run(cmd, cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise GitError(f"git checkout failed: {commit}")


def is_file_in_git_repo(file_path):
    real_path = os.path.realpath(file_path)
    dir_path = os.path.dirname(real_path)
    # pylint: disable=subprocess-run-check
    cmd = ["git", "rev-parse", "--is-inside-work-tree"]
    result = subprocess.run(
        cmd, cwd=dir_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.returncode == 0


def has_uncommited_changes() -> bool:
    cmd = ["git", "diff"]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True
    )
    if result.stdout:
        return True
    return False
