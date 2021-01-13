import os
import yaml
import tempfile
import copy
from subprocess import run, PIPE
from reconcile.utils.defer import defer


class PromtoolResult(object):
    '''This class represents a promtool command execution result'''
    def __init__(self, is_ok, message):
        self.is_ok = is_ok
        self.message = message

    def __str__(self):
        return str(self.message).replace('\n', '')

    def __bool__(self):
        return self.is_ok


def check_rule(yaml_spec):
    '''Run promtool check rules on the given yaml spec given as dict'''
    return _run_yaml_spec_cmd(cmd=['promtool', 'check', 'rules'],
                              yaml_spec=yaml_spec)


def run_test(test_yaml_spec, rule_files):
    '''Run promtool test rules

       params:

       test_yaml_spec: test yaml spec dict

       rule_files: dict indexed by rule path containing rule files yaml dicts
     '''
    temp_rule_files = {}
    try:
        for rule_file, yaml_spec in rule_files.items():
            with tempfile.NamedTemporaryFile(delete=False) as fp:
                fp.write(yaml.dump(yaml_spec).encode())
                temp_rule_files[rule_file] = fp.name
    except Exception as e:
        return PromtoolResult(False, f'Error building temp rule files: {e}')

    # build a test yaml prometheus files that uses the temp files created
    new_rule_files = []
    for rule_file in test_yaml_spec['rule_files']:
        if rule_file not in temp_rule_files:
            raise PromtoolResult(False, f'{rule_file} not in rule_files dict')

        new_rule_files.append(temp_rule_files[rule_file])

    temp_test_yaml_spec = copy.deepcopy(test_yaml_spec)
    temp_test_yaml_spec['rule_files'] = new_rule_files

    defer(lambda: _cleanup(temp_rule_files.values()))

    return _run_yaml_spec_cmd(cmd=['promtool', 'test', 'rules'],
                              yaml_spec=temp_test_yaml_spec)


def _run_yaml_spec_cmd(cmd, yaml_spec):
    try:
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(yaml.dump(yaml_spec).encode())
            fp.flush()
            cmd.append(fp.name)
            status = run(cmd, stdout=PIPE, stderr=PIPE)
    except Exception as e:
        return PromtoolResult(False, f'Error running promtool: {e}')

    if status.returncode != 0:
        message = 'Error running promtool'
        if status.stderr:
            message += ": " + status.stderr.decode()

        return PromtoolResult(False, message)

    return PromtoolResult(True, status.stdout.decode())


def _cleanup(paths):
    try:
        for path in paths:
            os.unlink(path)
    except Exception:
        pass
