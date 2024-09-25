import os
import subprocess


class GitError(Exception):
    pass


def clone(repo_url, wd, depth=None, verify=True):
    cmd = ["git"]
    if not verify:
        cmd += ["-c", "http.sslVerify=false"]
    cmd += ["clone"]
    if depth:
        cmd += ["--depth", str(depth)]
    cmd += [repo_url, wd]
    result = subprocess.run(cmd, cwd=wd, capture_output=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git clone failed: {repo_url}")


def current_ref(wd: str) -> str:
    try:
        # First try to get the current branch or tag
        cmd = ["git", "symbolic-ref", "--short", "HEAD"]
        result = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        # If not on a branch (detached HEAD), get the commit hash
        cmd = ["git", "rev-parse", "--short", "HEAD"]
        result = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, check=True)
        return result.stdout.strip()


def fetch(ref: str, wd: str, remote: str = "origin", depth: int | None = None):
    cmd = ["git", "fetch", remote, ref]
    if depth:
        cmd += ["--depth", str(depth)]
    result = subprocess.run(cmd, cwd=wd, capture_output=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git fetch failed: {ref}")


def checkout(ref: str, wd: str):
    if ref != current_ref(wd):
        fetch(ref, wd, depth=1)
    cmd = ["git", "checkout", ref]
    result = subprocess.run(cmd, cwd=wd, capture_output=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git checkout failed: {ref}")


def is_file_in_git_repo(file_path):
    real_path = os.path.realpath(file_path)
    dir_path = os.path.dirname(real_path)
    cmd = ["git", "rev-parse", "--is-inside-work-tree"]
    result = subprocess.run(cmd, cwd=dir_path, capture_output=True, check=False)
    return result.returncode == 0


def has_uncommited_changes() -> bool:
    cmd = ["git", "diff"]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True
    )
    return bool(result.stdout)


def show_uncommited_changes() -> str:
    cmd = ["git", "diff"]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True
    )
    return result.stdout.decode("utf-8")
