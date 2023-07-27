import json
import logging
import subprocess
from typing import Any


def state_rm_access_key(working_dirs, account, user):
    wd = working_dirs[account]
    init_result = subprocess.run(["terraform", "init"], check=False, cwd=wd)
    if init_result.returncode != 0:
        return False
    resource = "aws_iam_access_key.{}".format(user)
    result = subprocess.run(["terraform", "state", "rm", resource], check=False, cwd=wd)
    return result.returncode == 0


def _terraform_command(args: list[str], working_dir: str) -> (int, str, str):
    result = subprocess.run(
        args,
        capture_output=True,
        check=False,
        cwd=working_dir,
    )
    return_code = result.returncode
    stdout = result.stdout.decode("utf-8")
    stderr = result.stderr.decode("utf-8")
    return return_code, stdout, stderr


def show_json(working_dir: str, path: str) -> dict[str, Any]:
    """
    Run terraform show -no-color -json <path>.

    :param working_dir: The directory where the terraform files are located
    :param path: The path to the plan file
    :return: Deserialized JSON from the terraform show command
    """
    return_code, stdout, stderr = _terraform_command(
        args=["terraform", "show", "-no-color", "-json", path],
        working_dir=working_dir,
    )
    if return_code != 0:
        msg = f"[{path}] terraform show failed: {stderr}"
        logging.warning(msg)
        raise Exception(msg)
    return json.loads(stdout)


def init(working_dir: str) -> (int, str, str):
    """
    Run terraform init -input=false -no-color.

    :param working_dir: The directory where the terraform files are located
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "init", "-input=false", "-no-color"],
        working_dir=working_dir,
    )


def output(working_dir: str) -> (int, str, str):
    """
    Run terraform output -json.

    :param working_dir: The directory where the terraform files are located
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "output", "-json"],
        working_dir=working_dir,
    )


def plan(working_dir: str, out: str):
    """
    Run terraform plan -out=<out> -input=false -no-color.

    :param working_dir: The directory where the terraform files are located
    :param out: The path to the plan file
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "plan", f"-out={out}", "-input=false", "-no-color"],
        working_dir=working_dir,
    )


def apply(working_dir: str, dir_or_plan: str):
    """
    Run terraform apply -input=false -no-color <dir_or_plan>.

    :param working_dir: The directory where the terraform files are located
    :param dir_or_plan: The path to the directory or plan file
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "apply", "-input=false", "-no-color", dir_or_plan],
        working_dir=working_dir,
    )
