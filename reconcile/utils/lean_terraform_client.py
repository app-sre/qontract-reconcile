from subprocess import PIPE, Popen


def state_rm_access_key(working_dirs, account, user):
    wd = working_dirs[account]
    proc = Popen(['terraform', 'init'],
                 cwd=wd, stdout=PIPE, stderr=PIPE)
    proc.communicate()
    if proc.returncode != 0:
        return False
    resource = 'aws_iam_access_key.{}'.format(user)
    proc = Popen(['terraform', 'state', 'rm', resource],
                 cwd=wd, stdout=PIPE, stderr=PIPE)
    proc.communicate()
    return proc.returncode == 0
