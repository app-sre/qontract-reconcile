import json
import logging
import os
import sys
import re

from typing import Dict, Optional

import click
import sentry_sdk

from reconcile.utils import config
from reconcile.utils import gql

from reconcile.status import ExitCodes
from reconcile.status import RunningState

from reconcile.utils.gql import GqlApiErrorForbiddenSchema, GqlApiIntegrationNotFound
from reconcile.utils.aggregated_list import RunnerException
from reconcile.utils.binary import binary, binary_version
from reconcile.utils.environ import environ
from reconcile.utils.runtime.meta import IntegrationMeta
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.exceptions import PrintToFileInGitRepositoryError
from reconcile.utils.git import is_file_in_git_repo


TERRAFORM_VERSION = "0.13.7"
TERRAFORM_VERSION_REGEX = r"^Terraform\sv([\d]+\.[\d]+\.[\d]+)$"

OC_VERSION = "4.10.15"
OC_VERSION_REGEX = r"^Client\sVersion:\s([\d]+\.[\d]+\.[\d]+)$"

LOG_FMT = (
    "[%(asctime)s] [%(levelname)s] "
    "[%(filename)s:%(funcName)s:%(lineno)d] - %(message)s"
)
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def before_breadcrumb(crumb, hint):
    # https://docs.sentry.io/platforms/python/configuration/filtering/
    # Configure breadcrumb to filter error mesage
    if "category" in crumb and crumb["category"] == "subprocess":
        # remove cluster token
        crumb["message"] = re.sub(r"--token \S*\b", "--token ***", crumb["message"])
    return crumb


# Enable Sentry
if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(  # type: ignore[abstract] # pylint: disable=abstract-class-instantiated
        os.environ["SENTRY_DSN"], before_breadcrumb=before_breadcrumb
    )


def config_file(function):
    help_msg = "Path to configuration file in toml format."
    function = click.option(
        "--config",
        "configfile",
        required=True,
        default=os.environ.get("QONTRACT_CONFIG"),
        help=help_msg,
    )(function)
    return function


def log_level(function):
    function = click.option(
        "--log-level",
        help="log-level of the command. Defaults to INFO.",
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
    )(function)
    return function


def early_exit(function):
    help_msg = (
        "Runs integration in early exit mode. If the observed desired state of "
        "an integration does not change between the provided bundle SHA "
        "--early-exit-compare-sha and the current bundle sha, the integration "
        "exits without spending more time with reconciling."
    )
    function = click.option(
        "--early-exit-compare-sha",
        help=help_msg,
        default=lambda: os.environ.get("EARLY_EXIT_COMPARE_SHA", None),
    )(function)
    return function


def dry_run(function):
    help_msg = (
        "If `true`, it will only print the planned actions "
        "that would be performed, without executing them."
    )

    function = click.option("--dry-run/--no-dry-run", default=False, help=help_msg)(
        function
    )
    return function


def validate_schemas(function):
    help_msg = "Fail integration if it queries forbidden schemas"

    function = click.option(
        "--validate-schemas/--no-validate-schemas", default=True, help=help_msg
    )(function)
    return function


def dump_schemas(function):
    help_msg = "Dump schemas to a file"

    function = click.option("--dump-schemas", "dump_schemas_file", help=help_msg)(
        function
    )
    return function


def gql_sha_url(function):
    help_msg = (
        "If `false`, it will not use the sha_url endpoint "
        "of graphql (prevent stopping execution on data reload)."
    )

    function = click.option(
        "--gql-sha-url/--no-gql-sha-url", default=True, help=help_msg
    )(function)
    return function


def gql_url_print(function):
    help_msg = "If `false`, it will not print the url endpoint of graphql."

    function = click.option(
        "--gql-url-print/--no-gql-url-print", default=True, help=help_msg
    )(function)
    return function


def threaded(**kwargs):
    def f(function):
        opt = "--thread-pool-size"
        msg = "number of threads to run in parallel."
        function = click.option(opt, default=kwargs.get("default", 10), help=msg)(
            function
        )
        return function

    return f


def take_over(**kwargs):
    def f(function):
        help_msg = "manage resources exclusively (take over existing ones)."
        function = click.option(
            "--take-over/--no-take-over", help=help_msg, default=True
        )(function)
        return function

    return f


def internal(**kwargs):
    def f(function):
        help_msg = "manage resources in internal or external clusters only."
        function = click.option("--internal/--external", help=help_msg, default=None)(
            function
        )
        return function

    return f


def use_jump_host(**kwargs):
    def f(function):
        help_msg = "use jump host if defined."
        function = click.option(
            "--use-jump-host/--no-use-jump-host", help=help_msg, default=False
        )(function)
        return function

    return f


def print_only(function):
    function = click.option(
        "--print-only/--no-print-only",
        help="only print the config file.",
        default=False,
    )(function)

    return function


def print_to_file(function):
    function = click.option(
        "--print-to-file", help="print the config to file.", default=None
    )(function)

    return function


def config_name(function):
    function = click.option(
        "--config-name",
        help="jenkins config name to print out." "must works with --print-only mode",
        default=None,
    )(function)

    return function


def job_name(function):
    function = click.option(
        "--job-name", help="jenkins job name to print out.", default=None
    )(function)

    return function


def instance_name(function):
    function = click.option(
        "--instance-name", help="jenkins instance name to act on.", default=None
    )(function)

    return function


def throughput(function):
    function = click.option(
        "--io-dir", help="directory of input/output files.", default="throughput/"
    )(function)

    return function


def vault_input_path(function):
    function = click.option(
        "--vault-input-path", help="path in Vault to find input resources.", default=""
    )(function)

    return function


def vault_output_path(function):
    function = click.option(
        "--vault-output-path",
        help="path in Vault to store output resources.",
        default="",
    )(function)

    return function


def vault_throughput_path(function):
    function = click.option(
        "--vault-throughput-path",
        help="path in Vault to find input resources " "and store output resources.",
        default="",
    )(function)

    return function


def cluster_name(function):
    function = click.option(
        "--cluster-name", help="cluster name to act on.", default=None
    )(function)

    return function


def namespace_name(function):
    function = click.option(
        "--namespace-name", help="namespace name to act on.", default=None
    )(function)

    return function


def environment_name(function):
    function = click.option(
        "--environment-name",
        help="environment name to act on.",
        default=os.environ.get("ENVIRONMENT_NAME"),
    )(function)

    return function


def resource_kind(function):
    function = click.option("--resource-kind", help="kind to act on.", default=None)(
        function
    )

    return function


def account_name(function):
    function = click.option(
        "--account-name", help="aws account name to act on.", default=None
    )(function)

    return function


def gitlab_project_id(function):
    function = click.option(
        "--gitlab-project-id",
        help="gitlab project id to submit PRs to. "
        "not required if mergeRequestGateway "
        "is not set to gitlab",
        default=None,
    )(function)

    return function


def saas_file_name(function):
    function = click.option(
        "--saas-file-name", help="saas-file to act on.", default=None
    )(function)

    return function


def enable_deletion(**kwargs):
    def f(function):
        opt = "--enable-deletion/--no-enable-deletion"
        msg = "enable destroy/replace action."
        function = click.option(opt, default=kwargs.get("default", True), help=msg)(
            function
        )
        return function

    return f


def send_mails(**kwargs):
    def f(function):
        opt = "--send-mails/--no-send-mails"
        msg = "send email notification to users."
        function = click.option(opt, default=kwargs.get("default", False), help=msg)(
            function
        )
        return function

    return f


def enable_rebase(**kwargs):
    def f(function):
        opt = "--enable-rebase/--no-enable-rebase"
        msg = "enable the merge request rebase action."
        function = click.option(opt, default=kwargs.get("default", True), help=msg)(
            function
        )
        return function

    return f


def include_trigger_trace(function):
    help_msg = "If `true`, include traces of the triggering integration and reason."

    function = click.option(
        "--include-trigger-trace/--no-include-trigger-trace",
        default=False,
        help=help_msg,
    )(function)
    return function


def run_integration(func_container, ctx, *args, **kwargs):
    try:
        int_name = func_container.QONTRACT_INTEGRATION.replace("_", "-")
        running_state = RunningState()
        running_state.integration = int_name
    except AttributeError:
        sys.stderr.write("Integration missing QONTRACT_INTEGRATION.\n")
        sys.exit(ExitCodes.ERROR)

    unleash_feature_state = get_feature_toggle_state(int_name)
    if not unleash_feature_state:
        logging.info("Integration toggle is disabled, skipping integration.")
        sys.exit(ExitCodes.SUCCESS)

    dry_run = ctx.get("dry_run", False)
    early_exit_compare_sha = ctx.get("early_exit_compare_sha")

    try:
        # check if the integration can exit early because there is no difference
        # in desired state compared to the provided comparison bundle sha
        # early exit is only supported when the integration is started in
        # dry-run mode
        can_exit_early = (
            dry_run
            and early_exit_compare_sha
            and early_exit_integration(
                int_name, early_exit_compare_sha, func_container, args, kwargs
            )
        )
        if can_exit_early:
            logging.debug("No changes in desired state. Exit PR check early.")
        else:
            try:
                gql.init_from_config(
                    autodetect_sha=ctx["gql_sha_url"],
                    integration=int_name,
                    validate_schemas=ctx["validate_schemas"],
                    print_url=ctx["gql_url_print"],
                )
            except GqlApiIntegrationNotFound as e:
                sys.stderr.write(str(e) + "\n")
                sys.exit(ExitCodes.INTEGRATION_NOT_FOUND)
            func_container.run(dry_run, *args, **kwargs)
    except RunnerException as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(ExitCodes.ERROR)
    except GqlApiErrorForbiddenSchema as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(ExitCodes.FORBIDDEN_SCHEMA)
    finally:
        if ctx.get("dump_schemas_file"):
            gqlapi = gql.get_api()
            with open(ctx.get("dump_schemas_file"), "w") as f:
                f.write(json.dumps(gqlapi.get_queried_schemas()))


def early_exit_integration(
    int_name: str, compare_sha: str, func_container, *args, **kwargs
) -> bool:
    early_exit_desired_state_function = "early_exit_desired_state"
    # does the integration support early exit?
    if "early_exit_desired_state" not in dir(func_container):
        logging.warning(
            f"{int_name} does not support early exit. it does not offer a "
            f"function called {early_exit_desired_state_function}"
        )
        return False

    # get desired state from comparison bundle
    try:
        gql.init_from_config(
            sha=compare_sha,
            integration=int_name,
            validate_schemas=True,
            print_url=False,
        )
        previous_desired_state = func_container.early_exit_desired_state(
            *args, **kwargs
        )
    except Exception:
        logging.exception(
            f"Failed to fetch desired state for comparison bundle {compare_sha} failed"
        )
        return False

    # get desired state from current bundle
    try:
        gql.init_from_config(
            autodetect_sha=True,
            integration=int_name,
            validate_schemas=True,
            print_url=False,
        )
        current_desired_state = func_container.early_exit_desired_state(*args, **kwargs)
    except Exception:
        logging.exception("Failed to fetch desired state for current bundle failed")
        return False

    # compare
    from deepdiff import DeepDiff

    diff = DeepDiff(previous_desired_state, current_desired_state)
    return not diff


def init_log_level(log_level):
    level = getattr(logging, log_level) if log_level else logging.INFO
    logging.basicConfig(format=LOG_FMT, datefmt=LOG_DATEFMT, level=level)


@click.group()
@config_file
@dry_run
@early_exit
@validate_schemas
@dump_schemas
@gql_sha_url
@gql_url_print
@log_level
@click.pass_context
def integration(
    ctx,
    configfile,
    dry_run,
    early_exit_compare_sha,
    validate_schemas,
    dump_schemas_file,
    log_level,
    gql_sha_url,
    gql_url_print,
):
    ctx.ensure_object(dict)

    init_log_level(log_level)
    config.init_from_toml(configfile)
    ctx.obj["dry_run"] = dry_run
    ctx.obj["early_exit_compare_sha"] = early_exit_compare_sha
    ctx.obj["validate_schemas"] = validate_schemas
    ctx.obj["gql_sha_url"] = gql_sha_url
    ctx.obj["gql_url_print"] = gql_url_print
    ctx.obj["dump_schemas_file"] = dump_schemas_file


@integration.command(short_help="Manage AWS Route53 resources using Terraform.")
@print_to_file
@threaded()
@binary(["terraform", "git"])
@binary_version("terraform", ["version"], TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=True)
@account_name
@click.pass_context
def terraform_aws_route53(
    ctx, print_to_file, enable_deletion, thread_pool_size, account_name
):
    import reconcile.terraform_aws_route53

    run_integration(
        reconcile.terraform_aws_route53,
        ctx.obj,
        print_to_file,
        enable_deletion,
        thread_pool_size,
        account_name,
    )


@integration.command(short_help="Configures the teams and members in a GitHub org.")
@click.pass_context
def github(ctx):
    import reconcile.github_org

    run_integration(reconcile.github_org, ctx.obj)


@integration.command(short_help="Configures owners in a GitHub org.")
@click.pass_context
def github_owners(ctx):
    import reconcile.github_owners

    run_integration(reconcile.github_owners, ctx.obj)


@integration.command(short_help="Validate compliance of GitHub user profiles.")
@environ(["gitlab_pr_submitter_queue_url"])
@gitlab_project_id
@threaded()
@enable_deletion(default=False)
@send_mails(default=False)
@click.pass_context
def github_users(ctx, gitlab_project_id, thread_pool_size, enable_deletion, send_mails):
    import reconcile.github_users

    run_integration(
        reconcile.github_users,
        ctx.obj,
        gitlab_project_id,
        thread_pool_size,
        enable_deletion,
        send_mails,
    )


@integration.command(
    short_help="Scan GitHub repositories for leaked keys "
    "and remove them (only submits PR)."
)
@environ(["gitlab_pr_submitter_queue_url"])
@gitlab_project_id
@threaded()
@binary(["git", "git-secrets"])
@click.pass_context
def github_scanner(ctx, gitlab_project_id, thread_pool_size):
    import reconcile.github_scanner

    run_integration(
        reconcile.github_scanner, ctx.obj, gitlab_project_id, thread_pool_size
    )


@integration.command(short_help="Validates GitHub organization settings.")
@click.pass_context
def github_validator(ctx):
    import reconcile.github_validator

    run_integration(reconcile.github_validator, ctx.obj)


@integration.command(short_help="Configures ClusterRolebindings in OpenShift clusters.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_clusterrolebindings(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_clusterrolebindings

    run_integration(
        reconcile.openshift_clusterrolebindings,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(short_help="Configures Rolebindings in OpenShift clusters.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_rolebindings(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_rolebindings

    run_integration(
        reconcile.openshift_rolebindings,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(short_help="Manages OpenShift Groups.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_groups(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_groups

    run_integration(
        reconcile.openshift_groups, ctx.obj, thread_pool_size, internal, use_jump_host
    )


@integration.command(short_help="Deletion of users from OpenShift clusters.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_users(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_users

    run_integration(
        reconcile.openshift_users, ctx.obj, thread_pool_size, internal, use_jump_host
    )


@integration.command(
    short_help="Use OpenShift ServiceAccount tokens " "across namespaces/clusters."
)
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@vault_output_path
@click.pass_context
def openshift_serviceaccount_tokens(
    ctx, thread_pool_size, internal, use_jump_host, vault_output_path
):
    import reconcile.openshift_serviceaccount_tokens

    run_integration(
        reconcile.openshift_serviceaccount_tokens,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        vault_output_path,
    )


@integration.command(short_help="Manage Jenkins roles association via REST API.")
@click.pass_context
def jenkins_roles(ctx):
    import reconcile.jenkins_roles

    run_integration(reconcile.jenkins_roles, ctx.obj)


@integration.command(short_help="Manage Jenkins plugins installation via REST API.")
@click.pass_context
def jenkins_plugins(ctx):
    import reconcile.jenkins_plugins

    run_integration(reconcile.jenkins_plugins, ctx.obj)


@integration.command(
    short_help="Manage Jenkins jobs configurations using jenkins-jobs."
)
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@print_only
@config_name
@job_name
@instance_name
@throughput
@click.pass_context
def jenkins_job_builder(ctx, io_dir, print_only, config_name, job_name, instance_name):
    import reconcile.jenkins_job_builder

    run_integration(
        reconcile.jenkins_job_builder,
        ctx.obj,
        io_dir,
        print_only,
        config_name,
        job_name,
        instance_name,
    )


@integration.command(short_help="Clean up jenkins job history.")
@click.pass_context
def jenkins_job_builds_cleaner(ctx):
    import reconcile.jenkins_job_builds_cleaner

    run_integration(reconcile.jenkins_job_builds_cleaner, ctx.obj)


@integration.command(short_help="Delete Jenkins jobs in multiple tenant instances.")
@click.pass_context
def jenkins_job_cleaner(ctx):
    import reconcile.jenkins_job_cleaner

    run_integration(reconcile.jenkins_job_cleaner, ctx.obj)


@integration.command(short_help="Manage web hooks to Jenkins jobs.")
@click.pass_context
def jenkins_webhooks(ctx):
    import reconcile.jenkins_webhooks

    run_integration(reconcile.jenkins_webhooks, ctx.obj)


@integration.command(short_help="Remove webhooks to previous Jenkins instances.")
@click.pass_context
def jenkins_webhooks_cleaner(ctx):
    import reconcile.jenkins_webhooks_cleaner

    run_integration(reconcile.jenkins_webhooks_cleaner, ctx.obj)


@integration.command(short_help="Watch for changes in Jira boards and notify on Slack.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def jira_watcher(ctx):
    import reconcile.jira_watcher

    run_integration(reconcile.jira_watcher, ctx.obj)


@integration.command(
    short_help="Watch for changes in Unleah feature toggles " "and notify on Slack."
)
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def unleash_watcher(ctx):
    import reconcile.unleash_watcher

    run_integration(reconcile.unleash_watcher, ctx.obj)


@integration.command(
    short_help="Watches for OpenShift upgrades and sends notifications."
)
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@threaded()
@internal()
@use_jump_host()
@click.pass_context
def openshift_upgrade_watcher(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_upgrade_watcher

    run_integration(
        reconcile.openshift_upgrade_watcher,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(short_help="Manage Slack User Groups (channels and users).")
@click.pass_context
def slack_usergroups(ctx):
    import reconcile.slack_usergroups

    run_integration(reconcile.slack_usergroups, ctx.obj)


@integration.command(
    short_help="Manage Slack User Groups (channels and users) "
    "for OpenShift users notifications."
)
@click.pass_context
def slack_cluster_usergroups(ctx):
    import reconcile.slack_cluster_usergroups

    run_integration(reconcile.slack_cluster_usergroups, ctx.obj)


@integration.command(short_help="Manage integrations on GitLab projects.")
@click.pass_context
def gitlab_integrations(ctx):
    import reconcile.gitlab_integrations

    run_integration(reconcile.gitlab_integrations, ctx.obj)


@integration.command(short_help="Manage permissions on GitLab projects.")
@threaded()
@click.pass_context
def gitlab_permissions(ctx, thread_pool_size):
    import reconcile.gitlab_permissions

    run_integration(reconcile.gitlab_permissions, ctx.obj, thread_pool_size)


@integration.command(short_help="Manage issues and merge requests on GitLab projects.")
@click.option(
    "--wait-for-pipeline/--no-wait-for-pipeline",
    default=False,
    help="wait for pending/running pipelines before acting.",
)
@click.pass_context
def gitlab_housekeeping(ctx, wait_for_pipeline):
    import reconcile.gitlab_housekeeping

    run_integration(reconcile.gitlab_housekeeping, ctx.obj, wait_for_pipeline)


@integration.command(short_help="Listen to SQS and creates MRs out of the messages.")
@environ(["gitlab_pr_submitter_queue_url"])
@click.argument("gitlab-project-id")
@click.pass_context
def gitlab_mr_sqs_consumer(ctx, gitlab_project_id):
    import reconcile.gitlab_mr_sqs_consumer

    run_integration(reconcile.gitlab_mr_sqs_consumer, ctx.obj, gitlab_project_id)


@integration.command(short_help="Delete orphan AWS resources.")
@threaded()
@click.pass_context
def aws_garbage_collector(ctx, thread_pool_size):
    import reconcile.aws_garbage_collector

    run_integration(reconcile.aws_garbage_collector, ctx.obj, thread_pool_size)


@integration.command(short_help="Delete IAM access keys by access key ID.")
@threaded()
@account_name
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def aws_iam_keys(ctx, thread_pool_size, account_name):
    import reconcile.aws_iam_keys

    run_integration(
        reconcile.aws_iam_keys, ctx.obj, thread_pool_size, account_name=account_name
    )


@integration.command(short_help="Reset IAM user password by user reference.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def aws_iam_password_reset(ctx):
    import reconcile.aws_iam_password_reset

    run_integration(reconcile.aws_iam_password_reset, ctx.obj)


@integration.command(short_help="Share AMI and AMI tags between accounts.")
@click.pass_context
def aws_ami_share(ctx):
    import reconcile.aws_ami_share

    run_integration(reconcile.aws_ami_share, ctx.obj)


@integration.command(
    short_help="Generate AWS ECR image pull secrets and store them in Vault."
)
@vault_output_path
@click.pass_context
def aws_ecr_image_pull_secrets(ctx, vault_output_path):
    import reconcile.aws_ecr_image_pull_secrets

    run_integration(reconcile.aws_ecr_image_pull_secrets, ctx.obj, vault_output_path)


@integration.command(
    short_help="Scan AWS support cases for reports of leaked keys and "
    "remove them (only submits PR)"
)
@environ(["gitlab_pr_submitter_queue_url"])
@gitlab_project_id
@threaded()
@click.pass_context
def aws_support_cases_sos(ctx, gitlab_project_id, thread_pool_size):
    import reconcile.aws_support_cases_sos

    run_integration(
        reconcile.aws_support_cases_sos, ctx.obj, gitlab_project_id, thread_pool_size
    )


@integration.command(short_help="Manages OpenShift Resources.")
@threaded(default=20)
@binary(["oc", "ssh", "amtool"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@cluster_name
@namespace_name
@click.pass_context
def openshift_resources(
    ctx, thread_pool_size, internal, use_jump_host, cluster_name, namespace_name
):
    import reconcile.openshift_resources

    run_integration(
        reconcile.openshift_resources,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        cluster_name=cluster_name,
        namespace_name=namespace_name,
    )


@integration.command(short_help="Manage OpenShift resources defined in Saas files.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@environ(["gitlab_pr_submitter_queue_url"])
@gitlab_project_id
@threaded(default=20)
@throughput
@use_jump_host()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@click.option("--saas-file-name", default=None, help="saas-file to act on.")
@click.option("--env-name", default=None, help="environment to deploy to.")
@click.pass_context
def openshift_saas_deploy(
    ctx,
    thread_pool_size,
    io_dir,
    use_jump_host,
    saas_file_name,
    env_name,
    gitlab_project_id,
):
    import reconcile.openshift_saas_deploy

    run_integration(
        reconcile.openshift_saas_deploy,
        ctx.obj,
        thread_pool_size,
        io_dir,
        use_jump_host,
        saas_file_name,
        env_name,
        gitlab_project_id,
    )


@integration.command(short_help="A wrapper around openshift-saas-deploy.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@environ(["gitlab_pr_submitter_queue_url"])
@gitlab_project_id
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@throughput
@use_jump_host()
@click.pass_context
def openshift_saas_deploy_wrapper(
    ctx, thread_pool_size, io_dir, use_jump_host, gitlab_project_id
):
    import reconcile.openshift_saas_deploy_wrapper

    run_integration(
        reconcile.openshift_saas_deploy_wrapper,
        ctx.obj,
        thread_pool_size,
        io_dir,
        use_jump_host,
        gitlab_project_id,
    )


@integration.command(
    short_help="Runs openshift-saas-deploy for each saas-file that changed within a bundle."
)
@click.argument("gitlab-project-id")
@click.argument("gitlab-merge-request-id")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@environ(["gitlab_pr_submitter_queue_url"])  # do we need this???
@threaded()
@click.option(
    "--comparison-sha",
    help="bundle sha to compare to to find changes",
)
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@use_jump_host()
@click.pass_context
def openshift_saas_deploy_change_tester(
    ctx,
    gitlab_project_id,
    gitlab_merge_request_id,
    thread_pool_size,
    comparison_sha,
    use_jump_host,
):
    import reconcile.openshift_saas_deploy_change_tester

    run_integration(
        reconcile.openshift_saas_deploy_change_tester,
        ctx.obj,
        gitlab_project_id,
        gitlab_merge_request_id,
        thread_pool_size,
        comparison_sha,
        use_jump_host,
    )


@integration.command(short_help="Validates Saas files.")
@click.pass_context
def saas_file_validator(ctx):
    import reconcile.saas_file_validator

    run_integration(reconcile.saas_file_validator, ctx.obj)


@integration.command(short_help="Trigger deployments when a commit changed for a ref.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@include_trigger_trace
@click.pass_context
def openshift_saas_deploy_trigger_moving_commits(
    ctx, thread_pool_size, internal, use_jump_host, include_trigger_trace
):
    import reconcile.openshift_saas_deploy_trigger_moving_commits

    run_integration(
        reconcile.openshift_saas_deploy_trigger_moving_commits,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        include_trigger_trace,
    )


@integration.command(short_help="Trigger deployments when upstream job runs.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@include_trigger_trace
@click.pass_context
def openshift_saas_deploy_trigger_upstream_jobs(
    ctx, thread_pool_size, internal, use_jump_host, include_trigger_trace
):
    import reconcile.openshift_saas_deploy_trigger_upstream_jobs

    run_integration(
        reconcile.openshift_saas_deploy_trigger_upstream_jobs,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        include_trigger_trace,
    )


@integration.command(short_help="Trigger deployments when images are pushed.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@include_trigger_trace
@click.pass_context
def openshift_saas_deploy_trigger_images(
    ctx, thread_pool_size, internal, use_jump_host, include_trigger_trace
):
    import reconcile.openshift_saas_deploy_trigger_images

    run_integration(
        reconcile.openshift_saas_deploy_trigger_images,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        include_trigger_trace,
    )


@integration.command(short_help="Trigger deployments when configuration changes.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@include_trigger_trace
@click.pass_context
def openshift_saas_deploy_trigger_configs(
    ctx, thread_pool_size, internal, use_jump_host, include_trigger_trace
):
    import reconcile.openshift_saas_deploy_trigger_configs

    run_integration(
        reconcile.openshift_saas_deploy_trigger_configs,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        include_trigger_trace,
    )


@integration.command(short_help="Clean up deployment related resources.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_saas_deploy_trigger_cleaner(
    ctx, thread_pool_size, internal, use_jump_host
):
    import reconcile.openshift_saas_deploy_trigger_cleaner

    run_integration(
        reconcile.openshift_saas_deploy_trigger_cleaner,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(
    short_help="Manages custom resources for Tekton based deployments."
)
@threaded()
@internal()
@use_jump_host()
@saas_file_name
@click.pass_context
def openshift_tekton_resources(
    ctx, thread_pool_size, internal, use_jump_host, saas_file_name
):
    import reconcile.openshift_tekton_resources

    run_integration(
        reconcile.openshift_tekton_resources,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        saas_file_name,
    )


@integration.command(
    short_help="Manages labels on merge requests "
    "based on approver schema for saas files."
)
@throughput
@click.argument("gitlab-project-id")
@click.argument("gitlab-merge-request-id")
@click.option(
    "--compare/--no-compare",
    default=True,
    help="compare between current and desired state.",
)
@click.pass_context
def saas_file_owners(ctx, gitlab_project_id, gitlab_merge_request_id, io_dir, compare):
    import reconcile.saas_file_owners

    run_integration(
        reconcile.saas_file_owners,
        ctx.obj,
        gitlab_project_id,
        gitlab_merge_request_id,
        io_dir,
        compare,
    )


@integration.command(short_help="Determines if CI can be skipped.")
@click.argument("gitlab-project-id")
@click.argument("gitlab-merge-request-id")
@click.pass_context
def gitlab_ci_skipper(ctx, gitlab_project_id, gitlab_merge_request_id):
    import reconcile.gitlab_ci_skipper

    run_integration(
        reconcile.gitlab_ci_skipper, ctx.obj, gitlab_project_id, gitlab_merge_request_id
    )


@integration.command(
    short_help="Guesses and adds labels to merge requests "
    "according to changed paths."
)
@click.argument("gitlab-project-id")
@click.argument("gitlab-merge-request-id")
@click.pass_context
def gitlab_labeler(ctx, gitlab_project_id, gitlab_merge_request_id):
    import reconcile.gitlab_labeler

    run_integration(
        reconcile.gitlab_labeler, ctx.obj, gitlab_project_id, gitlab_merge_request_id
    )


@integration.command(short_help="Manages labels on OpenShift namespaces.")
@threaded()
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_namespace_labels(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_namespace_labels

    run_integration(
        reconcile.openshift_namespace_labels,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(short_help="Manages OpenShift Namespaces.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_namespaces(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_namespaces

    run_integration(
        reconcile.openshift_namespaces,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(short_help="Manages OpenShift NetworkPolicies.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_network_policies(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.openshift_network_policies

    run_integration(
        reconcile.openshift_network_policies,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(short_help="Manages OpenShift LimitRange objects.")
@threaded()
@take_over()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_limitranges(ctx, thread_pool_size, internal, use_jump_host, take_over):
    import reconcile.openshift_limitranges

    run_integration(
        reconcile.openshift_limitranges,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        take_over,
    )


@integration.command(short_help="Manages OpenShift ResourceQuota objects.")
@threaded()
@take_over()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_resourcequotas(ctx, thread_pool_size, internal, use_jump_host, take_over):
    import reconcile.openshift_resourcequotas

    run_integration(
        reconcile.openshift_resourcequotas,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        take_over,
    )


@integration.command(short_help="Manages OpenShift Secrets from Vault.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@cluster_name
@namespace_name
@click.pass_context
def openshift_vault_secrets(
    ctx, thread_pool_size, internal, use_jump_host, cluster_name, namespace_name
):
    import reconcile.openshift_vault_secrets

    run_integration(
        reconcile.openshift_vault_secrets,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        cluster_name=cluster_name,
        namespace_name=namespace_name,
    )


@integration.command(short_help="Manages OpenShift Routes.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@cluster_name
@namespace_name
@click.pass_context
def openshift_routes(
    ctx, thread_pool_size, internal, use_jump_host, cluster_name, namespace_name
):
    import reconcile.openshift_routes

    run_integration(
        reconcile.openshift_routes,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        cluster_name=cluster_name,
        namespace_name=namespace_name,
    )


@integration.command(short_help="Configures the teams and members in Quay.")
@click.pass_context
def quay_membership(ctx):
    import reconcile.quay_membership

    run_integration(reconcile.quay_membership, ctx.obj)


@integration.command(
    short_help="Mirrors external images into Google Container Registry."
)
@click.pass_context
@binary(["skopeo"])
def gcr_mirror(ctx):
    import reconcile.gcr_mirror

    run_integration(reconcile.gcr_mirror, ctx.obj)


@integration.command(short_help="Mirrors external images into Quay.")
@click.option(
    "-d",
    "--control-file-dir",
    help="Directory where integration control file will be created. This file controls "
    "when to compare tags (very slow) apart from mirroring new tags.",
)
@click.option(
    "-t/-n",
    "--compare-tags/--no-compare-tags",
    help="Forces the integration to do or do not do tag comparation no matter what the "
    "control file says.",
    default=None,
)
@click.option(
    "-c",
    "--compare-tags-interval",
    help="Time to wait between compare-tags runs (in seconds). It defaults to 86400 "
    "(24h).",
    type=int,
    default=86400,
)
@click.option(
    "-i",
    "--image",
    help="Only considers this image to mirror. It can be specified multiple times.",
    multiple=True,
)
@click.pass_context
@binary(["skopeo"])
def quay_mirror(ctx, control_file_dir, compare_tags, compare_tags_interval, image):
    import reconcile.quay_mirror

    run_integration(
        reconcile.quay_mirror,
        ctx.obj,
        control_file_dir,
        compare_tags,
        compare_tags_interval,
        image,
    )


@integration.command(short_help="Mirrors entire Quay orgs.")
@click.option(
    "-d",
    "--control-file-dir",
    help="Directory where integration control file will be created. This file controls "
    "when to compare tags (very slow) apart from mirroring new tags.",
)
@click.option(
    "-t/-n",
    "--compare-tags/--no-compare-tags",
    help="Forces the integration to do or do not do tag comparation no matter what the "
    "control file says.",
    default=None,
)
@click.option(
    "-c",
    "--compare-tags-interval",
    help="Time to wait between compare-tags runs (in seconds). It defaults to 86400 "
    "(8h).",
    type=int,
    default=28800,
)
@click.option(
    "-o",
    "--org",
    help="Only considers this organisation to mirror. It can be specified multiple "
    "times.",
    multiple=True,
)
@click.option(
    "-r",
    "--repository",
    help="Only considers this repository to mirror. It can be specified multiple "
    "times.",
    multiple=True,
)
@click.pass_context
@binary(["skopeo"])
def quay_mirror_org(
    ctx, control_file_dir, compare_tags, compare_tags_interval, org, repository
):
    import reconcile.quay_mirror_org

    run_integration(
        reconcile.quay_mirror_org,
        ctx.obj,
        control_file_dir,
        compare_tags,
        compare_tags_interval,
        org,
        repository,
    )


@integration.command(short_help="Creates and Manages Quay Repos.")
@click.pass_context
def quay_repos(ctx):
    import reconcile.quay_repos

    run_integration(reconcile.quay_repos, ctx.obj)


@integration.command(short_help="Manage permissions for Quay Repositories.")
@click.pass_context
def quay_permissions(ctx):
    import reconcile.quay_permissions

    run_integration(reconcile.quay_permissions, ctx.obj)


@integration.command(short_help="Removes users which are not found in LDAP search.")
@click.argument("gitlab-project-id")
@click.pass_context
def ldap_users(ctx, gitlab_project_id):
    import reconcile.ldap_users

    run_integration(reconcile.ldap_users, ctx.obj, gitlab_project_id)


@integration.command(short_help="Manage AWS Resources using Terraform.")
@print_to_file
@vault_output_path
@threaded(default=20)
@binary(["terraform", "oc", "git"])
@binary_version("terraform", ["version"], TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@internal()
@use_jump_host()
@enable_deletion(default=False)
@account_name
@click.option(
    "--light/--full",
    default=False,
    help="run without executing terraform plan and apply.",
)
@click.pass_context
def terraform_resources(
    ctx,
    print_to_file,
    enable_deletion,
    thread_pool_size,
    internal,
    use_jump_host,
    light,
    vault_output_path,
    account_name,
):
    import reconcile.terraform_resources

    if print_to_file and is_file_in_git_repo(print_to_file):
        raise PrintToFileInGitRepositoryError(print_to_file)
    run_integration(
        reconcile.terraform_resources,
        ctx.obj,
        print_to_file,
        enable_deletion,
        thread_pool_size,
        internal,
        use_jump_host,
        light,
        vault_output_path,
        account_name=account_name,
    )


@integration.command(short_help="Manage Cloudflare Resources using Terraform.")
@print_to_file
@enable_deletion(default=False)
@threaded(default=20)
@binary(["terraform"])
@binary_version("terraform", ["version"], TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@click.pass_context
def terraform_cloudflare_resources(
    ctx,
    print_to_file,
    enable_deletion,
    thread_pool_size,
):
    import reconcile.terraform_cloudflare_resources

    run_integration(
        reconcile.terraform_cloudflare_resources,
        ctx.obj,
        print_to_file,
        enable_deletion,
        thread_pool_size,
    )


@integration.command(short_help="Manage AWS users using Terraform.")
@print_to_file
@threaded(default=20)
@binary(["terraform", "gpg", "git"])
@binary_version("terraform", ["version"], TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=True)
@send_mails(default=True)
@account_name
@click.pass_context
def terraform_users(
    ctx,
    print_to_file,
    enable_deletion,
    thread_pool_size,
    send_mails,
    account_name,
):
    import reconcile.terraform_users

    if print_to_file and is_file_in_git_repo(print_to_file):
        raise PrintToFileInGitRepositoryError(print_to_file)
    run_integration(
        reconcile.terraform_users,
        ctx.obj,
        print_to_file,
        enable_deletion,
        thread_pool_size,
        send_mails,
        account_name=account_name,
    )


@integration.command()
@print_to_file
@threaded()
@binary(["terraform", "git"])
@binary_version("terraform", ["version"], TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=False)
@account_name
@click.pass_context
def terraform_vpc_peerings(
    ctx, print_to_file, enable_deletion, thread_pool_size, account_name
):
    import reconcile.terraform_vpc_peerings

    if print_to_file and is_file_in_git_repo(print_to_file):
        raise PrintToFileInGitRepositoryError(print_to_file)
    run_integration(
        reconcile.terraform_vpc_peerings,
        ctx.obj,
        print_to_file,
        enable_deletion,
        thread_pool_size,
        account_name,
    )


@integration.command(
    short_help="Validates that VPC peerings do not exist between public and internal clusters."
)
@click.pass_context
def vpc_peerings_validator(ctx):
    import reconcile.vpc_peerings_validator

    run_integration(
        reconcile.vpc_peerings_validator,
        ctx.obj,
    )


@integration.command(short_help="Manages Transit Gateway attachments.")
@print_to_file
@threaded()
@binary(["terraform", "git"])
@binary_version("terraform", ["version"], TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=False)
@click.pass_context
def terraform_tgw_attachments(ctx, print_to_file, enable_deletion, thread_pool_size):
    import reconcile.terraform_tgw_attachments

    if print_to_file and is_file_in_git_repo(print_to_file):
        raise PrintToFileInGitRepositoryError(print_to_file)
    run_integration(
        reconcile.terraform_tgw_attachments,
        ctx.obj,
        print_to_file,
        enable_deletion,
        thread_pool_size,
    )


@integration.command(
    short_help="Accept GitHub repository invitations for known repositories."
)
@click.pass_context
def github_repo_invites(ctx):
    import reconcile.github_repo_invites

    run_integration(reconcile.github_repo_invites, ctx.obj)


@integration.command(short_help="Validates permissions in github repositories.")
@click.argument("instance-name")
@click.pass_context
def github_repo_permissions_validator(ctx, instance_name):
    import reconcile.github_repo_permissions_validator

    run_integration(reconcile.github_repo_permissions_validator, ctx.obj, instance_name)


@integration.command(short_help="Manage GitLab group members.")
@click.pass_context
def gitlab_members(ctx):
    import reconcile.gitlab_members

    run_integration(reconcile.gitlab_members, ctx.obj)


@integration.command(short_help="Create GitLab projects.")
@click.pass_context
def gitlab_projects(ctx):
    import reconcile.gitlab_projects

    run_integration(reconcile.gitlab_projects, ctx.obj)


@integration.command(short_help="Manage membership in OpenShift groups via OCM.")
@threaded()
@click.pass_context
def ocm_groups(ctx, thread_pool_size):
    import reconcile.ocm_groups

    run_integration(reconcile.ocm_groups, ctx.obj, thread_pool_size)


@integration.command(short_help="Manages clusters via OCM.")
@environ(["gitlab_pr_submitter_queue_url"])
@gitlab_project_id
@threaded()
@click.pass_context
def ocm_clusters(ctx, gitlab_project_id, thread_pool_size):
    import reconcile.ocm_clusters

    run_integration(
        reconcile.ocm_clusters, ctx.obj, gitlab_project_id, thread_pool_size
    )


@integration.command(short_help="Manage External Configuration labels in OCM.")
@threaded()
@click.pass_context
def ocm_external_configuration_labels(ctx, thread_pool_size):
    import reconcile.ocm_external_configuration_labels

    run_integration(
        reconcile.ocm_external_configuration_labels, ctx.obj, thread_pool_size
    )


@integration.command(short_help="Manage Machine Pools in OCM.")
@threaded()
@click.pass_context
def ocm_machine_pools(ctx, thread_pool_size):
    import reconcile.ocm_machine_pools

    run_integration(reconcile.ocm_machine_pools, ctx.obj, thread_pool_size)


@integration.command(short_help="Manage Upgrade Policy schedules in OCM.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def ocm_upgrade_scheduler(ctx):
    import reconcile.ocm_upgrade_scheduler

    run_integration(reconcile.ocm_upgrade_scheduler, ctx.obj)


@integration.command(short_help="Manages cluster Addons in OCM.")
@threaded()
@click.pass_context
def ocm_addons(ctx, thread_pool_size):
    import reconcile.ocm_addons

    run_integration(reconcile.ocm_addons, ctx.obj, thread_pool_size)


@integration.command(
    short_help="Grants AWS infrastructure access " "to members in AWS groups via OCM."
)
@click.pass_context
def ocm_aws_infrastructure_access(ctx):
    import reconcile.ocm_aws_infrastructure_access

    run_integration(reconcile.ocm_aws_infrastructure_access, ctx.obj)


@integration.command(short_help="Manage GitHub Identity Providers in OCM.")
@vault_input_path
@click.pass_context
def ocm_github_idp(ctx, vault_input_path):
    import reconcile.ocm_github_idp

    run_integration(reconcile.ocm_github_idp, ctx.obj, vault_input_path)


@integration.command(short_help="Manage additional routers in OCM.")
@click.pass_context
def ocm_additional_routers(ctx):
    import reconcile.ocm_additional_routers

    run_integration(reconcile.ocm_additional_routers, ctx.obj)


@integration.command(short_help="Send email notifications to app-interface audience.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def email_sender(ctx):
    import reconcile.email_sender

    run_integration(reconcile.email_sender, ctx.obj)


@integration.command(short_help="Watch for Sentry access requests and notify on Slack.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def sentry_helper(ctx):
    import reconcile.sentry_helper

    run_integration(reconcile.sentry_helper, ctx.obj)


@integration.command(
    short_help="Send emails to users based on " "requests submitted to app-interface."
)
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def requests_sender(ctx):
    import reconcile.requests_sender

    run_integration(reconcile.requests_sender, ctx.obj)


@integration.command(short_help="Validate dependencies are defined for each service.")
@click.pass_context
def service_dependencies(ctx):
    import reconcile.service_dependencies

    run_integration(reconcile.service_dependencies, ctx.obj)


@integration.command(short_help="Configure and enforce sentry instance configuration.")
@click.pass_context
def sentry_config(ctx):
    import reconcile.sentry_config

    run_integration(reconcile.sentry_config, ctx.obj)


@integration.command(short_help="Runs SQL Queries against app-interface RDS resources.")
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@enable_deletion(default=False)
@click.pass_context
def sql_query(ctx, enable_deletion):
    import reconcile.sql_query

    run_integration(reconcile.sql_query, ctx.obj, enable_deletion)


@integration.command(
    short_help="Manages labels on gitlab merge requests "
    "based on OWNERS files schema."
)
@threaded()
@click.pass_context
def gitlab_owners(ctx, thread_pool_size):
    import reconcile.gitlab_owners

    run_integration(reconcile.gitlab_owners, ctx.obj, thread_pool_size)


@integration.command(short_help="Ensures that forks of App Interface are compliant.")
@click.argument("gitlab-project-id")
@click.argument("gitlab-merge-request-id")
@click.argument("gitlab-maintainers-group", required=False)
@click.pass_context
def gitlab_fork_compliance(
    ctx, gitlab_project_id, gitlab_merge_request_id, gitlab_maintainers_group
):
    import reconcile.gitlab_fork_compliance

    run_integration(
        reconcile.gitlab_fork_compliance,
        ctx.obj,
        gitlab_project_id,
        gitlab_merge_request_id,
        gitlab_maintainers_group,
    )


@integration.command(
    short_help="Collects the ImageManifestVuln CRs from all the clusters "
    "and posts them to Dashdotdb."
)
@threaded(default=2)
@click.pass_context
def dashdotdb_cso(ctx, thread_pool_size):
    import reconcile.dashdotdb_cso

    run_integration(reconcile.dashdotdb_cso, ctx.obj, thread_pool_size)


@integration.command(
    short_help="Collects the DeploymentValidations from all the clusters "
    "and posts them to Dashdotdb."
)
@threaded(default=2)
@click.pass_context
@cluster_name
def dashdotdb_dvo(ctx, thread_pool_size, cluster_name):
    import reconcile.dashdotdb_dvo

    run_integration(reconcile.dashdotdb_dvo, ctx.obj, thread_pool_size, cluster_name)


@integration.command(
    short_help="Collects the ServiceSloMetrics from all the clusters "
    "and posts them to Dashdotdb."
)
@threaded(default=2)
@click.pass_context
def dashdotdb_slo(ctx, thread_pool_size):
    import reconcile.dashdotdb_slo

    run_integration(reconcile.dashdotdb_slo, ctx.obj, thread_pool_size)


@integration.command(short_help="Mirrors OCP release images.")
@click.pass_context
def ocp_release_mirror(ctx):
    import reconcile.ocp_release_mirror

    run_integration(reconcile.ocp_release_mirror, ctx.obj)


@integration.command(
    short_help="Collects OSD mirror information and " "updates app-interface via MR."
)
@gitlab_project_id
@click.pass_context
def osd_mirrors_data_updater(ctx, gitlab_project_id):
    import reconcile.osd_mirrors_data_updater

    run_integration(reconcile.osd_mirrors_data_updater, ctx.obj, gitlab_project_id)


@integration.command(short_help="Mirrors external images into AWS ECR.")
@threaded()
@click.pass_context
def ecr_mirror(ctx, thread_pool_size):
    import reconcile.ecr_mirror

    run_integration(reconcile.ecr_mirror, ctx.obj, thread_pool_size)


@integration.command(short_help="Manages Kafka clusters via OCM.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@vault_throughput_path
@click.pass_context
def kafka_clusters(
    ctx, thread_pool_size, internal, use_jump_host, vault_throughput_path
):
    import reconcile.kafka_clusters

    run_integration(
        reconcile.kafka_clusters,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
        vault_throughput_path,
    )


@integration.command(
    short_help="Ensures all integrations are defined in App-Interface."
)
@click.pass_context
def integrations_validator(ctx):
    import reconcile.integrations_validator

    run_integration(
        reconcile.integrations_validator,
        ctx.obj,
        reconcile.cli.integration.commands.keys(),
    )


@integration.command(short_help="Tests prometheus rules using promtool.")
@threaded()
@binary(["promtool"])
@cluster_name
@click.pass_context
def prometheus_rules_tester(ctx, thread_pool_size, cluster_name):
    import reconcile.prometheus_rules_tester

    run_integration(
        reconcile.prometheus_rules_tester, ctx.obj, thread_pool_size, cluster_name
    )


@integration.command(short_help="Tests templating of resources.")
@click.pass_context
def template_tester(ctx):
    import reconcile.template_tester

    run_integration(reconcile.template_tester, ctx.obj)


@integration.command(
    short_help="Validate queries to maintain consumer schema compatibility."
)
@click.pass_context
def query_validator(ctx):
    import reconcile.query_validator

    run_integration(reconcile.query_validator, ctx.obj)


@integration.command(short_help="Manages SendGrid teammates for a given account.")
@click.pass_context
def sendgrid_teammates(ctx):
    import reconcile.sendgrid_teammates

    run_integration(reconcile.sendgrid_teammates, ctx.obj)


@integration.command(short_help="Maps ClusterDeployment resources to Cluster IDs.")
@vault_output_path
@click.pass_context
def cluster_deployment_mapper(ctx, vault_output_path):
    import reconcile.cluster_deployment_mapper

    run_integration(reconcile.cluster_deployment_mapper, ctx.obj, vault_output_path)


@integration.command(short_help="Get resources from clusters and store in Vault.")
@namespace_name
@resource_kind
@vault_output_path
@click.pass_context
def resource_scraper(ctx, namespace_name, resource_kind, vault_output_path):
    import reconcile.resource_scraper

    run_integration(
        reconcile.resource_scraper,
        ctx.obj,
        namespace_name,
        resource_kind,
        vault_output_path,
    )


@integration.command(short_help="Manages user access for GABI instances.")
@threaded()
@binary(["oc", "ssh"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def gabi_authorized_users(ctx, thread_pool_size, internal, use_jump_host):
    import reconcile.gabi_authorized_users

    run_integration(
        reconcile.gabi_authorized_users,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(short_help="Manage Traffic Director services in Dyn DNS.")
@enable_deletion(default=False)
@click.pass_context
def dyn_traffic_director(ctx, enable_deletion):
    import reconcile.dyn_traffic_director

    run_integration(reconcile.dyn_traffic_director, ctx.obj, enable_deletion)


@integration.command(
    short_help="Manages components on statuspage.io hosted status pages."
)
@click.pass_context
def status_page_components(ctx):
    import reconcile.status_page_components

    run_integration(reconcile.status_page_components, ctx.obj)


@integration.command(
    short_help="Manages Prometheus Probe resources for blackbox-exporter"
)
@threaded()
@internal()
@use_jump_host()
@click.pass_context
def blackbox_exporter_endpoint_monitoring(
    ctx, thread_pool_size, internal, use_jump_host
):
    import reconcile.blackbox_exporter_endpoint_monitoring

    run_integration(
        reconcile.blackbox_exporter_endpoint_monitoring,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


@integration.command(
    short_help="Manages Prometheus Probe resources for signalfx exporter"
)
@threaded()
@internal()
@use_jump_host()
@click.pass_context
def signalfx_prometheus_endpoint_monitoring(
    ctx, thread_pool_size, internal, use_jump_host
):
    import reconcile.signalfx_endpoint_monitoring

    run_integration(
        reconcile.signalfx_endpoint_monitoring,
        ctx.obj,
        thread_pool_size,
        internal,
        use_jump_host,
    )


def parse_image_tag_from_ref(ctx, param, value) -> Optional[Dict[str, str]]:
    if value:
        result = {}
        for v in value:
            if v.count("=") != 1 or v.startswith("=") or v.endswith("="):
                logging.error(
                    f'image-tag-from-ref "{v}" should be of the form "<env_name>=<ref>"'
                )
                sys.exit(ExitCodes.ERROR)
            k, v = v.split("=")
            result[k] = v
        return result
    return None


@integration.command(short_help="Manages Qontract Reconcile integrations.")
@environment_name
@threaded()
@binary(["oc", "ssh", "helm"])
@binary_version("oc", ["version", "--client"], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.option(
    "--image-tag-from-ref",
    "-r",
    help="git ref to use as IMAGE_TAG for given environment. example: '--image-tag-from-ref app-interface-dev=master'.",
    multiple=True,
    callback=parse_image_tag_from_ref,
)
@click.pass_context
def integrations_manager(
    ctx,
    environment_name,
    thread_pool_size,
    internal,
    use_jump_host,
    image_tag_from_ref,
):
    import reconcile.integrations_manager

    run_integration(
        reconcile.integrations_manager,
        ctx.obj,
        environment_name,
        get_integration_cli_meta(),
        thread_pool_size,
        internal,
        use_jump_host,
        image_tag_from_ref,
    )


@integration.command(
    short_help="Detects owners for changes in app-interface PRs and allows them to self-service merge."
)
@click.argument("gitlab-project-id")
@click.argument("gitlab-merge-request-id")
@click.option(
    "--comparison-sha",
    help="bundle sha to compare to to find changes",
)
@click.option(
    "--change-type-processing-mode",
    help="if `limited` (default) the integration will not make any final decisions on the MR, but if `authoritative` it will ",
    default=os.environ.get("CHANGE_TYPE_PROCESSING_MODE", "limited"),
    type=click.Choice(["limited", "authoritative"], case_sensitive=True),
)
@click.option(
    "--mr-management",
    is_flag=True,
    default=os.environ.get("MR_MANAGEMENT", False),
    help="Manage MR labels and comments (default to false)",
)
@click.pass_context
def change_owners(
    ctx,
    gitlab_project_id,
    gitlab_merge_request_id,
    comparison_sha,
    change_type_processing_mode,
    mr_management,
):
    import reconcile.change_owners.change_owners

    run_integration(
        reconcile.change_owners.change_owners,
        ctx.obj,
        gitlab_project_id,
        gitlab_merge_request_id,
        comparison_sha,
        change_type_processing_mode,
        mr_management,
    )


def get_integration_cli_meta() -> dict[str, IntegrationMeta]:
    """
    returns all integrations known to cli.py via click introspection

    todo(geoberle, janboll) - this needs rework in the long run, especially since go-integrations
    are becoming relevant and this kind of meta programming just solves the python part, and even
    the python part is not solved in a robust enough way
    """
    integration_meta = {}
    for integration_name in integration.list_commands(None):  # type: ignore
        integration_cmd = integration.get_command(None, integration_name)  # type: ignore
        integration_meta[integration_name] = IntegrationMeta(
            name=integration_name,
            args=[p.opts[0] for p in integration_cmd.params if p.opts and len(p.opts) > 0],  # type: ignore
            short_help=integration_cmd.short_help,  # type: ignore
        )
    return integration_meta
