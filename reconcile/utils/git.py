import os
import subprocess


class GitError(Exception):
    pass


def clone(
    repo_url: str,
    wd: str,
    depth: int | None = None,
    verify: bool | None = True,
    ref: str | None = None,
    token: str | None = None,
):
    cmd = ["git"]
    if not verify:
        cmd += ["-c", "http.sslVerify=false"]
    cmd += ["clone"]
    if depth:
        cmd += ["--depth", str(depth)]
    if ref:
        cmd += ["--branch", ref]
    if token:
        cmd.append(repo_url.replace("https://", f"https://{token}@"))
    else:
        cmd.append(repo_url)
    cmd += [wd]
    os.makedirs(wd, exist_ok=True)
    result = subprocess.run(cmd, cwd=wd, capture_output=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git clone failed: {repo_url}: {result}")


def checkout(commit, wd):
    cmd = ["git", "checkout", commit]
    result = subprocess.run(cmd, cwd=wd, capture_output=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git checkout failed: {commit}")


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
    if result.stdout:
        return True
    return False


def show_uncommited_changes() -> str:
    cmd = ["git", "diff"]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True
    )
    return result.stdout.decode("utf-8")
