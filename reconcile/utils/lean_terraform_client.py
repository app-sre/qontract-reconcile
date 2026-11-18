from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def state_rm_access_key(
    working_dirs: Mapping[str, str], account: str, user: str, key_id: str
) -> bool:
    """Forget the selected key or succeed if its binding is already absent."""
    wd = working_dirs[account]
    return_code, _, _ = init(wd)
    if return_code:
        logging.error("[%s] Terraform init failed for IAM key rotation", account)
        return False

    # Resolve by ID without an address filter: Terraform errors on a missing
    # address filter, but returns an empty list for an absent ID.
    return_code, stdout, _ = _terraform_command(
        ["terraform", "state", "list", f"-id={key_id}"], wd
    )
    if return_code:
        logging.error("[%s] Terraform state list failed for IAM key rotation", account)
        return False
    addresses = stdout.strip().splitlines()
    if not addresses:
        logging.info(
            "[%s] IAM key binding for %s is absent, waiting for replacement",
            account,
            user,
        )
        return True

    resource = f"aws_iam_access_key.{user}"
    if addresses != [resource]:
        logging.error(
            "[%s] Unexpected Terraform binding for IAM user %s", account, user
        )
        return False

    return_code, _, _ = _terraform_command(
        ["terraform", "state", "rm", "-no-color", resource], wd
    )
    if return_code:
        logging.error("[%s] Terraform state rm failed for %s", account, resource)
        return False
    logging.info("[%s] Removed Terraform binding %s", account, resource)
    return True


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
