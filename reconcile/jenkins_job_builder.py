import logging
import sys
from collections.abc import Callable
from typing import (
    Any,
    Optional,
)

from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.jjb_client import JJB
from reconcile.utils.secret_reader import (
    SecretReader,
    SecretReaderBase,
)
from reconcile.utils.state import init_state

QUERY = """
{
  jenkins_configs: jenkins_configs_v1 {
    name
    app {
      name
    }
    instance {
      name
      serverUrl
      token {
        path
        field
        version
        format
      }
      deleteMethod
    }
    type
    config
    config_path {
      content
    }
  }
}
"""

QONTRACT_INTEGRATION = "jenkins-job-builder"
GENERATE_TYPE = ["jobs", "views"]


def get_jenkins_configs():
    gqlapi = gql.get_api()
    return gqlapi.query(QUERY)["jenkins_configs"]


def collect_configs(
    instance_name: Optional[str], config_name: Optional[str]
) -> list[dict[str, Any]]:
    configs = get_jenkins_configs()
    if instance_name is not None:
        configs = [n for n in configs if n["instance"]["name"] == instance_name]
        if not configs:
            raise ValueError(f"instance name {instance_name} is not found")
    if config_name is not None:
        configs = [
            n
            for n in configs
            if n["type"] not in GENERATE_TYPE or n["name"] == config_name
        ]
        if not configs:
            raise ValueError(f"config name {config_name} is not found")

    return configs


def init_jjb(
    secret_reader: SecretReaderBase,
    instance_name: Optional[str] = None,
    config_name: Optional[str] = None,
    print_only: bool = False,
) -> JJB:
    configs = collect_configs(instance_name, config_name)
    return JJB(configs, secret_reader=secret_reader, print_only=print_only)


def validate_repos_and_admins(jjb: JJB):
    jjb_repos = jjb.get_repos()
    app_int_repos = queries.get_repos()
    missing_repos = [r for r in jjb_repos if r not in app_int_repos]
    for r in missing_repos:
        logging.error(f"repo is missing from codeComponents: {r}")
    jjb_admins = jjb.get_admins()
    app_int_users = queries.get_users()
    app_int_bots = queries.get_bots()
    external_users = queries.get_external_users()
    github_usernames = (
        [u.get("github_username") for u in app_int_users]
        + [b.get("github_username") for b in app_int_bots]
        + [u.get("github_username") for u in external_users]
    )
    unknown_admins = [a for a in jjb_admins if a not in github_usernames]
    for a in unknown_admins:
        logging.warning("admin is missing from users: {}".format(a))
    if missing_repos:
        sys.exit(1)


@defer
def run(
    dry_run: bool,
    io_dir: str = "throughput/",
    print_only: bool = False,
    config_name: Optional[str] = None,
    job_name: Optional[str] = None,
    instance_name: Optional[str] = None,
    defer: Optional[Callable] = None,
) -> None:
    if not print_only and config_name is not None:
        raise Exception("--config-name must works with --print-only mode")
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    jjb: JJB = init_jjb(secret_reader, instance_name, config_name, print_only)
    if defer:
        defer(jjb.cleanup)

    if print_only:
        jjb.print_jobs(job_name=job_name)
        if config_name is not None:
            jjb.generate(io_dir, "printout")
        sys.exit(0)

    state = init_state(QONTRACT_INTEGRATION, secret_reader)
    if defer:
        defer(state.cleanup)

    if dry_run:
        validate_repos_and_admins(jjb)
        jjb.generate(io_dir, "desired")
        jjb.overwrite_configs(state)
        jjb.generate(io_dir, "current")
        jjb.print_diffs(io_dir, instance_name)
    else:
        jjb.update()
        configs = jjb.get_configs()
        for name, desired_config in configs.items():
            state.add(name, value=desired_config, force=True)
