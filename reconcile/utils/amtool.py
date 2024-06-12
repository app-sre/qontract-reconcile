import re
import tempfile
from collections.abc import Mapping
from subprocess import (
    CalledProcessError,
    run,
)

AMTOOL_VERSION = ["0.24.0"]
AMTOOL_VERSION_REGEX = r"^amtool,\sversion\s([\d]+\.[\d]+\.[\d]+).+$"


class AmtoolResult:
    """This class represents a amtool command execution result"""

    def __init__(self, is_ok: bool, message: str) -> None:
        self.is_ok = is_ok
        self.message = message

    def __str__(self) -> str:
        return str(self.message).replace("\n", "")

    def __bool__(self) -> bool:
        return self.is_ok


def check_config(yaml_config: str) -> AmtoolResult:
    """Run amtool check rules on the given yaml string"""

    with tempfile.NamedTemporaryFile(mode="w+", encoding="locale") as fp:
        fp.write(yaml_config)
        fp.flush()
        cmd = ["amtool", "check-config", fp.name]
        result = _run_cmd(cmd)

    return result


def config_routes_test(yaml_config: str, labels: Mapping[str, str]) -> AmtoolResult:
    labels_lst = [f"{key}={value}" for key, value in labels.items()]
    with tempfile.NamedTemporaryFile(mode="w+", encoding="locale") as fp:
        fp.write(yaml_config)
        fp.flush()
        cmd = ["amtool", "config", "routes", "test", "--config.file", fp.name]
        cmd.extend(labels_lst)
        result = _run_cmd(cmd)

    return result


def version() -> AmtoolResult:
    """Returns the version parsed from amtool --version"""
    result = _run_cmd(["amtool", "--version"])

    pattern = re.compile("^amtool, version (?P<version>[^ ]+) .+")
    if m := pattern.match(result.message):
        return AmtoolResult(True, m.group("version"))

    return AmtoolResult(False, f"Unexpected amtool --version output {result.message}")


def _run_cmd(cmd: list[str]) -> AmtoolResult:
    try:
        result = run(cmd, capture_output=True, check=True)
    except CalledProcessError as e:
        msg = f'Error running amtool command [{" ".join(cmd)}]'
        if e.stdout:
            msg += f" {e.stdout.decode()}"
        if e.stderr:
            msg += f" {e.stderr.decode()}"

        return AmtoolResult(False, msg)

    # some amtool commands return also in stderr even in non-error
    output = result.stdout.decode() + result.stderr.decode()

    return AmtoolResult(True, output)
