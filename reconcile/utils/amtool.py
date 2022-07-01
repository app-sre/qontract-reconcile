import tempfile
from subprocess import run, PIPE, CalledProcessError


class AmtoolResult:
    """This class represents a amtool command execution result"""

    def __init__(self, is_ok, message):
        self.is_ok = is_ok
        self.message = message

    def __str__(self):
        return str(self.message).replace("\n", "")

    def __bool__(self):
        return self.is_ok


def check_config(yaml_str):
    """Run amtool check rules on the given yaml string"""
    return _run_yaml_str_cmd(cmd=["amtool", "check-config"], yaml_str=yaml_str)


def _run_yaml_str_cmd(cmd, yaml_str):
    try:
        with tempfile.NamedTemporaryFile(mode="w+") as fp:
            fp.write(yaml_str)
            fp.flush()
            cmd.append(fp.name)
            result = run(cmd, stdout=PIPE, stderr=PIPE, check=True)
    except CalledProcessError as e:
        msg = f'Error running amtool command [{" ".join(cmd)}]'
        if e.stdout:
            msg += f" {e.stdout.decode()}"
        if e.stderr:
            msg += f" {e.stderr.decode()}"

        return AmtoolResult(False, msg)

    return AmtoolResult(True, result.stdout.decode())
