import json
import logging
import os
import subprocess
from collections.abc import Mapping
from typing import Any


def state_rm_access_key(
    working_dirs: Mapping[str, str], account: str, user: str
) -> bool:
    wd = working_dirs[account]
    init_result = subprocess.run(["terraform", "init"], check=False, cwd=wd)
    if init_result.returncode != 0:
        return False
    resource = f"aws_iam_access_key.{user}"
    result = subprocess.run(["terraform", "state", "rm", resource], check=False, cwd=wd)
    return result.returncode == 0


def state_update_access_key_status(
    working_dirs: Mapping[str, str], keys_by_account: Mapping[str, list[dict[str, str]]]
) -> bool:
    """
    Update terraform state to reflect access key status changes for multiple keys.
    This uses terraform import to sync the current AWS state.
    """
    overall_success = True

    for account, keys in keys_by_account.items():
        if not keys:
            continue

        wd = working_dirs[account]
        init_result = subprocess.run(["terraform", "init"], check=False, cwd=wd)
        if init_result.returncode != 0:
            logging.warning(f"Failed to init terraform for account {account}")
            overall_success = False
            continue

        # Import all keys for this account in batch
        # https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_access_key#import
        for key_info in keys:
            user = key_info["user"]
            key_id = key_info["key_id"]

            resource = f"aws_iam_access_key.{user}"
            import_result = subprocess.run(
                ["terraform", "import", resource, key_id],
                check=False,
                cwd=wd,
                capture_output=True,
            )

            if import_result.returncode != 0:
                logging.warning(
                    f"Failed to import terraform state for {resource}: {import_result.stderr.decode()}"
                )
                overall_success = False

    return overall_success


def _compute_terraform_env(
    env: Mapping[str, str] | None = None,
) -> Mapping[str, str]:
    default_env = os.environ.copy()
    return default_env if env is None else {**default_env, **env}


def _terraform_command(
    args: list[str],
    working_dir: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    result = subprocess.run(
        args,
        capture_output=True,
        check=False,
        cwd=working_dir,
        env=_compute_terraform_env(env),
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


def init(
    working_dir: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """
    Run terraform init -input=false -no-color.

    :param working_dir: The directory where the terraform files are located
    :param env: Environment variables to pass to the terraform command
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "init", "-input=false", "-no-color"],
        working_dir=working_dir,
        env=env,
    )


def output(
    working_dir: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """
    Run terraform output -json.

    :param working_dir: The directory where the terraform files are located
    :param env: Environment variables to pass to the terraform command
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "output", "-json"],
        working_dir=working_dir,
        env=env,
    )


def plan(
    working_dir: str,
    out: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """
    Run terraform plan -out=<out> -input=false -no-color.

    :param working_dir: The directory where the terraform files are located
    :param out: The path to the plan file
    :param env: Environment variables to pass to the terraform command
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "plan", f"-out={out}", "-input=false", "-no-color"],
        working_dir=working_dir,
        env=env,
    )


def apply(
    working_dir: str,
    dir_or_plan: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """
    Run terraform apply -input=false -no-color <dir_or_plan>.

    :param working_dir: The directory where the terraform files are located
    :param dir_or_plan: The path to the directory or plan file
    :param env: Environment variables to pass to the terraform command
    :return: (return_code, stdout, stderr)
    """
    return _terraform_command(
        args=["terraform", "apply", "-input=false", "-no-color", dir_or_plan],
        working_dir=working_dir,
        env=env,
    )
