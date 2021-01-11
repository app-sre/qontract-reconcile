import json
import logging

from subprocess import PIPE, Popen


def state_rm_access_key(working_dirs, account, user):
    wd = working_dirs[account]
    proc = Popen(['terraform', 'init'],
                 cwd=wd, stdout=PIPE, stderr=PIPE)
    proc.communicate()
    if proc.returncode:
        return False
    resource = 'aws_iam_access_key.{}'.format(user)
    proc = Popen(['terraform', 'state', 'rm', resource],
                 cwd=wd, stdout=PIPE, stderr=PIPE)
    proc.communicate()
    return proc.returncode == 0


def show_json(working_dir, out_file):
    proc = Popen(['terraform', 'show', '-json', out_file],
                 cwd=working_dir, stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate()
    if proc.returncode:
        logging.warning(err)
        raise Exception('terraform show failed: ' + str(err))
    return json.loads(out)
