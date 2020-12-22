import yaml
import tempfile
from subprocess import run, PIPE


class PromtoolError(Exception):
    pass


def check_rule(yaml_spec):
    try:
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(yaml.dump(yaml_spec).encode())
            fp.flush()
            cmd = ['promtool', 'check', 'rules', fp.name]
            status = run(cmd, stdout=PIPE, stderr=PIPE)
    except Exception as e:
        raise PromtoolError(f'Error building promtool file: {e}')

    if status.returncode != 0:
        message = 'Error running promtool'
        if status.stderr:
            message += ": " + status.stderr.decode()

        raise PromtoolError(message)

    return status.stdout
