import yaml
import tempfile
from subprocess import run, PIPE


class PromtoolResult(object):
    def __init__(self, is_ok, message):
        self.is_ok = is_ok
        self.message = message

    def __str__(self):
        return str(self.message).replace('\n', '')

    def __bool__(self):
        return self.is_ok


def check_rule(yaml_spec):
    try:
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(yaml.dump(yaml_spec).encode())
            fp.flush()
            cmd = ['promtool', 'check', 'rules', fp.name]
            status = run(cmd, stdout=PIPE, stderr=PIPE)
    except Exception as e:
        return PromtoolResult(False, f'Error building promtool file: {e}')

    if status.returncode != 0:
        message = 'Error running promtool'
        if status.stderr:
            message += ": " + status.stderr.decode()

        return PromtoolResult(False, message)

    return PromtoolResult(True, status.stdout.decode())
