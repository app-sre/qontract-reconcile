import tempfile
from typing import Mapping
from subprocess import run, PIPE, CalledProcessError


class AmtoolResult:
    """This class represents a amtool command execution result"""

    def __init__(self, is_ok, message):
        self.is_ok = is_ok
        self.message = message

    def __str__(self) -> str:
        return str(self.message).replace("\n", "")

    def __bool__(self) -> bool:
        return self.is_ok


def check_config(yaml_config: str) -> AmtoolResult:
    """Run amtool check rules on the given yaml string"""

    with tempfile.NamedTemporaryFile(mode="w+") as fp:
        fp.write(yaml_config)
        fp.flush()
        cmd = ["amtool", "check-config", fp.name]
        result = _run_cmd(cmd)

    return result


def config_routes_test(yaml_config: str, labels: Mapping[str, str]) -> AmtoolResult:
    labels_lst = [f"{key}={value}" for key, value in labels.items()]
    with tempfile.NamedTemporaryFile(mode="w+") as fp:
        fp.write(yaml_config)
        fp.flush()
        cmd = ["amtool", "config", "routes", "test", "--config.file", fp.name]
        cmd.extend(labels_lst)
        result = _run_cmd(cmd)

    return result


def _run_cmd(cmd: list[str]) -> AmtoolResult:
    try:
        result = run(cmd, stdout=PIPE, stderr=PIPE, check=True)
    except CalledProcessError as e:
        msg = f'Error running amtool command [{" ".join(cmd)}]'
        if e.stdout:
            msg += f" {e.stdout.decode()}"
        if e.stderr:
            msg += f" {e.stderr.decode()}"

        return AmtoolResult(False, msg)

    return AmtoolResult(True, result.stdout.decode())
