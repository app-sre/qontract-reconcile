import subprocess


def generate() -> subprocess.CompletedProcess:
    return _run("generate")


def _run(sub_command: str) -> subprocess.CompletedProcess:
    cmd = ["make", sub_command]
    return subprocess.run(cmd, check=True)
