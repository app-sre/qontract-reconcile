import json
import logging
import subprocess


def state_rm_access_key(working_dirs, account, user):
    wd = working_dirs[account]
    init_result = subprocess.run(["terraform", "init"], check=False, cwd=wd)
    if init_result.returncode != 0:
        return False
    resource = "aws_iam_access_key.{}".format(user)
    result = subprocess.run(["terraform", "state", "rm", resource], check=False, cwd=wd)
    return result.returncode == 0


def show_json(working_dir, out_file):
    result = subprocess.run(
        ["terraform", "show", "-no-color", "-json", out_file],
        capture_output=True,
        check=False,
        cwd=working_dir,
    )
    if result.returncode != 0:
        msg = f"[{out_file}] terraform show failed: {result.stderr.decode('utf-8')}"
        logging.warning(msg)
        raise Exception(msg)
    return json.loads(result.stdout)
