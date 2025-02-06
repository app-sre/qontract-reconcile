import os
import subprocess


class GitError(Exception):
    pass


def clone(
    repo_url: str, wd: str, depth: int | None = None, verify: bool | None = True
) -> None:
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


def rev_parse(ref: str, wd: str) -> str:
    cmd = ["git", "rev-parse", ref]
    result = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def is_current_ref(ref: str, wd: str) -> bool:
    return rev_parse("HEAD", wd) == rev_parse(ref, wd)


def fetch(
    ref: str,
    wd: str,
    remote: str = "origin",
    depth: int | None = None,
    verify: bool = True,
) -> None:
    cmd = ["git"]
    if not verify:
        cmd += ["-c", "http.sslVerify=false"]
    cmd += ["fetch", remote, ref]
    if depth:
        cmd += ["--depth", str(depth)]
    result = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git fetch failed for {ref}: {result.stderr}")


def checkout(
    ref: str,
    wd: str,
    verify: bool = True,
) -> None:
    if not is_current_ref(ref, wd):
        fetch(ref, wd, depth=1, verify=verify)
    cmd = ["git", "checkout", ref]
    result = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git checkout failed for {ref}: {result.stderr}")


def is_file_in_git_repo(file_path: str) -> bool:
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
