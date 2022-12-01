import base64
import functools
import json
import os
import re
import sys
from collections import defaultdict
from contextlib import suppress
from datetime import datetime
from operator import itemgetter
from typing import Optional

import click
import requests
import yaml

import reconcile.gitlab_housekeeping as glhk
import reconcile.ocm_upgrade_scheduler as ous
import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb
import reconcile.terraform_resources as tfr
import reconcile.terraform_users as tfu
import reconcile.terraform_vpc_peerings as tfvpc
from reconcile import queries
from reconcile.change_owners.change_owners import (
    fetch_change_type_processors,
    fetch_self_service_roles,
)
from reconcile.checkpoint import report_invalid_metadata
from reconcile.cli import config_file
from reconcile.jenkins_job_builder import init_jjb
from reconcile.prometheus_rules_tester import get_data_from_jinja_test_template
from reconcile.slack_base import slackapi_from_queries
from reconcile.utils import (
    amtool,
    config,
    dnsutils,
    gql,
    promtool,
)
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.environ import environ
from reconcile.utils.external_resources import (
    PROVIDER_AWS,
    get_external_resource_specs,
    managed_external_resources,
)
from reconcile.utils.gitlab_api import (
    GitLabApi,
    MRState,
    MRStatus,
)
from reconcile.utils.jjb_client import JJB
from reconcile.utils.mr.labels import (
    SAAS_FILE_UPDATE,
    SELF_SERVICEABLE,
)
from reconcile.utils.oc import OC_Map
from reconcile.utils.ocm import OCMMap
from reconcile.utils.output import print_output
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import parse_semver
from reconcile.utils.state import State
from reconcile.utils.terraform_client import TerraformClient as Terraform
from tools.cli_commands.gpg_encrypt import (
    GPGEncryptCommand,
    GPGEncryptCommandData,
)
from tools.sre_checkpoints import (
    full_name,
    get_latest_sre_checkpoints,
)


def output(function):
    function = click.option(
        "--output",
        "-o",
        help="output type",
        default="table",
        type=click.Choice(["table", "md", "json", "yaml"]),
    )(function)
    return function


def sort(function):
    function = click.option(
        "--sort", "-s", help="sort output", default=True, type=bool
    )(function)
    return function


def to_string(function):
    function = click.option(
        "--to-string", help="stringify output", default=False, type=bool
    )(function)
    return function


@click.group()
@config_file
@click.pass_context
def root(ctx, configfile):
    ctx.ensure_object(dict)
    config.init_from_toml(configfile)
    gql.init_from_config()


@root.group()
@output
@sort
@to_string
@click.pass_context
def get(ctx, output, sort, to_string):
    ctx.obj["options"] = {
        "output": output,
        "sort": sort,
        "to_string": to_string,
    }


@root.group()
@output
@click.pass_context
def describe(ctx, output):
    ctx.obj["options"] = {
        "output": output,
    }


@get.command()
@click.pass_context
def settings(ctx):
    settings = queries.get_app_interface_settings()
    columns = ["vault", "kubeBinary", "mergeRequestGateway"]
    print_output(ctx.obj["options"], [settings], columns)


@get.command()
@click.argument("name", default="")
@click.pass_context
def aws_accounts(ctx, name):
    accounts = queries.get_aws_accounts(name=name)
    if not accounts:
        print("no aws accounts found")
        sys.exit(1)
    columns = ["name", "consoleUrl"]
    print_output(ctx.obj["options"], accounts, columns)


@get.command()
@click.argument("name", default="")
@click.pass_context
def clusters(ctx, name):
    clusters = queries.get_clusters()
    if name:
        clusters = [c for c in clusters if c["name"] == name]

    for c in clusters:
        jh = c.get("jumpHost")
        if jh:
            c["sshuttle"] = f"sshuttle -r {jh['hostname']} {c['network']['vpc']}"

    columns = ["name", "consoleUrl", "prometheusUrl", "sshuttle"]
    print_output(ctx.obj["options"], clusters, columns)


@get.command()
@click.argument("name", default="")
@click.pass_context
def cluster_upgrades(ctx, name):
    settings = queries.get_app_interface_settings()

    clusters = queries.get_clusters()

    clusters_ocm = [c for c in clusters if c.get("ocm") is not None and c.get("auth")]

    ocm_map = OCMMap(clusters=clusters_ocm, settings=settings)

    clusters_data = []
    for c in clusters:
        if name and c["name"] != name:
            continue

        if not c.get("spec"):
            continue

        data = {
            "name": c["name"],
            "id": c["spec"]["id"],
            "external_id": c["spec"].get("external_id"),
        }

        upgrade_policy = c["upgradePolicy"]

        if upgrade_policy:
            data["upgradePolicy"] = upgrade_policy.get("schedule_type")

        if data.get("upgradePolicy") == "automatic":
            data["schedule"] = c["upgradePolicy"]["schedule"]
            ocm = ocm_map.get(c["name"])
            if ocm:
                upgrade_policy = ocm.get_upgrade_policies(c["name"])
                if upgrade_policy and len(upgrade_policy) > 0:
                    next_run = upgrade_policy[0].get("next_run")
                    if next_run:
                        data["next_run"] = next_run
        else:
            data["upgradePolicy"] = "manual"

        clusters_data.append(data)

    columns = ["name", "upgradePolicy", "schedule", "next_run"]

    print_output(ctx.obj["options"], clusters_data, columns)


@get.command()
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def version_history(ctx):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get("upgradePolicy") is not None]
    ocm_map = OCMMap(clusters=clusters, settings=settings)

    history = ous.get_version_history(
        dry_run=True, upgrade_policies=[], ocm_map=ocm_map
    )

    results = []
    for ocm_name, history_data in history.items():
        for version, version_data in history_data["versions"].items():
            if not version:
                continue
            for workload, workload_data in version_data["workloads"].items():
                item = {
                    "ocm": ocm_name,
                    "version": parse_semver(version),
                    "workload": workload,
                    "soak_days": round(workload_data["soak_days"], 2),
                    "clusters": ", ".join(workload_data["reporting"]),
                }
                results.append(item)
    columns = ["ocm", "version", "workload", "soak_days", "clusters"]
    ctx.obj["options"]["to_string"] = True
    print_output(ctx.obj["options"], results, columns)


def soaking_days(history, upgrades, workload, only_soaking):
    soaking = {}
    for version in upgrades:
        for h in history.values():
            with suppress(KeyError):
                workload_data = h["versions"][version]["workloads"][workload]
                soaking[version] = round(workload_data["soak_days"], 2)
        if not only_soaking and version not in soaking:
            soaking[version] = 0
    return soaking


def get_upgrade_policies_data(
    clusters,
    md_output,
    workload=None,
    show_only_soaking_upgrades=False,
    by_workload=False,
):
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=clusters,
        settings=settings,
        init_version_gates=True,
    )
    current_state = ous.fetch_current_state(clusters, ocm_map)
    desired_state = ous.fetch_desired_state(clusters, ocm_map)

    history = ous.get_version_history(
        dry_run=True, upgrade_policies=[], ocm_map=ocm_map
    )

    results = []

    def soaking_str(soaking, upgrade_policy, upgradeable_version):
        upgrade_version = upgrade_policy.get("version")
        upgrade_next_run = upgrade_policy.get("next_run")
        upgrade_emoji = "💫"
        if upgrade_next_run:
            dt = datetime.strptime(upgrade_next_run, "%Y-%m-%dT%H:%M:%SZ")
            now = datetime.utcnow()
            if dt > now:
                upgrade_emoji = "⏰"
            hours_ago = (now - dt).total_seconds() / 3600
            if hours_ago > 6:  # 6 hours
                upgrade_emoji = f"💫 - started {hours_ago:.1f}h ago❗️"
        sorted_soaking = sorted(soaking.items(), key=lambda x: parse_semver(x[0]))
        if md_output:
            for i, data in enumerate(sorted_soaking):
                v, s = data
                if v == upgrade_version:
                    sorted_soaking[i] = (v, f"{s} {upgrade_emoji}")
                elif v == upgradeable_version:
                    sorted_soaking[i] = (v, f"{s} 🎉")
        return ", ".join([f"{v} ({s})" for v, s in sorted_soaking])

    for c in desired_state:
        cluster_name, version = c["cluster"], c["current_version"]
        channel, schedule = c["channel"], c.get("schedule")
        soakdays = c.get("conditions", {}).get("soakDays")
        mutexes = c.get("conditions", {}).get("mutexes") or []
        sector = ""
        if c.get("conditions", {}).get("sector"):
            sector = c["conditions"]["sector"].name
        ocm_org = ocm_map.get(cluster_name)
        ocm_spec = ocm_org.clusters[cluster_name]
        item = {
            "ocm": ocm_org.name,
            "cluster": cluster_name,
            "id": ocm_spec.spec.id,
            "api": ocm_spec.server_url,
            "console": ocm_spec.console_url,
            "domain": ocm_spec.domain,
            "version": version,
            "channel": channel,
            "schedule": schedule,
            "sector": sector,
            "soak_days": soakdays,
            "mutexes": ", ".join(mutexes),
        }

        if "workloads" not in c:
            results.append(item)
            continue

        upgrades = get_available_upgrades(ocm_org, version, channel)

        current = [c for c in current_state if c["cluster"] == cluster_name]
        upgrade_policy = {}
        if current and current[0]["schedule_type"] == "manual":
            upgrade_policy = current[0]

        upgradeable_version = ous.upgradeable_version(c, history, ocm_org)

        workload_soaking_upgrades = {}
        for w in c.get("workloads", []):
            if not workload or workload == w:
                s = soaking_days(history, upgrades, w, show_only_soaking_upgrades)
                workload_soaking_upgrades[w] = s

        if by_workload:
            for w, soaking in workload_soaking_upgrades.items():
                i = item.copy()
                i.update(
                    {
                        "workload": w,
                        "soaking_upgrades": soaking_str(
                            soaking, upgrade_policy, upgradeable_version
                        ),
                    }
                )
                results.append(i)
        else:
            workloads = sorted(c.get("workloads", []))
            w = ", ".join(workloads)
            soaking = {}
            for v in upgrades:
                soaks = [s.get(v, 0) for s in workload_soaking_upgrades.values()]
                min_soaks = min(soaks)
                if not show_only_soaking_upgrades or min_soaks > 0:
                    soaking[v] = min_soaks
            item.update(
                {
                    "workload": w,
                    "soaking_upgrades": soaking_str(
                        soaking, upgrade_policy, upgradeable_version
                    ),
                }
            )
            results.append(item)

    return results


upgrade_policies_output_description = """
The data below shows upgrade information for each clusters:
* `version` is the current openshift version on the cluster
* `channel` is the OCM upgrade channel being tracked by the cluster
* `schedule` is the cron-formatted schedule for cluster upgrades
* `mutexes` are named locks a cluster needs to acquire in order to get upgraded.
Only one cluster can acquire a given mutex at a given time. A cluster needs to
acquire all its mutexes in order to get upgraded. Mutexes are held for the full
duration of the cluster upgrade.
* `soak_days` is the minimum number of days a given version must have been
running on other clusters with the same workload to be considered for an
upgrade.
* `workload` is a list of workload names that are running on the cluster
* `sector` is the name of the OCM sector the cluster is part of. Sector
dependencies are defined per OCM organization. A cluster can be upgraded to a
version only if all clusters running the same workloads in previous sectors
already run at least that version.
* `soaking_upgrades` lists all available upgrades available on the OCM channel
for that cluster. The number in parenthesis shows the number of days this
version has been running on other clusters with the same workloads. By
comparing with the `soak_days` columns, you can see when a version is close to
be upgraded to.
  * A 🎉 is displayed for versions which have soaked enough and are ready to be
upgraded to.
  * A ⏰ is displayed for versions scheduled to be upgraded to.
  * A 💫 is displayed for versions which are being upgraded to. Upgrades taking
more than 6 hours will be highlighted.
"""


@get.command()
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.option("--cluster", default=None, help="cluster to display.")
@click.option("--workload", default=None, help="workload to display.")
@click.option(
    "--show-only-soaking-upgrades/--no-show-only-soaking-upgrades",
    default=False,
    help="show upgrades which are not currently soaking.",
)
@click.option(
    "--by-workload/--no-by-workload",
    default=False,
    help="show upgrades for each workload individually "
    "rather than grouping them for the whole cluster",
)
@click.pass_context
def cluster_upgrade_policies(
    ctx,
    cluster=None,
    workload=None,
    show_only_soaking_upgrades=False,
    by_workload=False,
):
    md_output = ctx.obj["options"]["output"] == "md"
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get("upgradePolicy") is not None]
    if cluster:
        clusters = [c for c in clusters if cluster == c["name"]]
    if workload:
        clusters = [
            c for c in clusters if workload in c["upgradePolicy"].get("workloads", [])
        ]

    results = get_upgrade_policies_data(
        clusters, md_output, workload, show_only_soaking_upgrades, by_workload
    )

    if md_output:
        fields = [
            {"key": "cluster", "sortable": True},
            {"key": "version", "sortable": True},
            {"key": "channel", "sortable": True},
            {"key": "schedule"},
            {"key": "sector", "sortable": True},
            {"key": "mutexes", "sortable": True},
            {"key": "soak_days", "sortable": True},
            {"key": "workload"},
            {"key": "soaking_upgrades"},
        ]
        md = """
{}

```json:table
{}
```
        """
        md = md.format(
            upgrade_policies_output_description,
            json.dumps(
                {"fields": fields, "items": results, "filter": True, "caption": ""},
                indent=1,
            ),
        )
        print(md)
    else:
        columns = [
            "cluster",
            "version",
            "channel",
            "schedule",
            "sector",
            "mutexes",
            "soak_days",
            "workload",
            "soaking_upgrades",
        ]
        ctx.obj["options"]["to_string"] = True
        print_output(ctx.obj["options"], results, columns)


@functools.lru_cache
def get_available_upgrades(ocm, version, channel):
    return ocm.get_available_upgrades(version, channel)


@get.command()
@click.pass_context
def ocm_fleet_upgrade_policies(
    ctx,
):
    md_output = ctx.obj["options"]["output"] == "md"
    ocm_specs = queries.get_openshift_cluster_managers()

    clusters = []

    for ocm_spec in ocm_specs:
        upgrade_policy_clusters = ocm_spec.get("upgradePolicyClusters")
        if not upgrade_policy_clusters:
            continue

        # patch clusters items with their ocm instance
        for c in upgrade_policy_clusters:
            c["ocm"] = ocm_spec

        clusters.extend(upgrade_policy_clusters)

    results = get_upgrade_policies_data(clusters, md_output)

    if md_output:
        print(upgrade_policies_output_description)
        fields = [
            {"key": "cluster", "sortable": True},
            {"key": "version", "sortable": True},
            {"key": "channel", "sortable": True},
            {"key": "schedule"},
            {"key": "sector", "sortable": True},
            {"key": "mutexes", "sortable": True},
            {"key": "soak_days", "sortable": True},
            {"key": "workload"},
            {"key": "soaking_upgrades"},
        ]
        ocm_orgs = sorted({o["ocm"] for o in results})
        ocm_org_section = """
# {}

```json:table
{}
```
        """
        for ocm_org in ocm_orgs:
            data = [o for o in results if o["ocm"] == ocm_org]
            json_data = json.dumps(
                {"fields": fields, "items": data, "filter": True, "caption": ""},
                indent=1,
            )
            print(ocm_org_section.format(ocm_org, json_data))

    else:
        columns = [
            "ocm",
            "cluster",
            "version",
            "channel",
            "schedule",
            "sector",
            "mutexes",
            "soak_days",
            "workload",
            "soaking_upgrades",
        ]
        ctx.obj["options"]["to_string"] = True
        print_output(ctx.obj["options"], results, columns)


@get.command()
@click.argument("name", default="")
@click.pass_context
def clusters_network(ctx, name):
    clusters = queries.get_clusters()
    if name:
        clusters = [c for c in clusters if c["name"] == name]

    columns = ["name", "network.vpc", "network.service", "network.pod"]
    # TODO(mafriedm): fix this
    # do not sort
    ctx.obj["options"]["sort"] = False
    print_output(ctx.obj["options"], clusters, columns)


def ocm_aws_infrastructure_access_switch_role_links_data() -> list[dict]:
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get("ocm") is not None]
    accounts = {a["uid"]: a["name"] for a in queries.get_aws_accounts()}
    ocm_map = OCMMap(clusters=clusters, settings=settings)

    results = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        ocm = ocm_map.get(cluster_name)
        role_grants = ocm.get_aws_infrastructure_access_role_grants(cluster_name)
        for user_arn, access_level, _, switch_role_link in role_grants:
            user = user_arn.split("/")[1]
            account_id = user_arn.split(":")[4]
            account_name = accounts.get(account_id, "")
            src_login = f"{user} @ [{account_id} ({account_name})](https://{account_id}.signin.aws.amazon.com/console)"
            item = {
                "cluster": cluster_name,
                "user": user,
                "user_arn": user_arn,
                "source_login": src_login,
                "access_level": access_level,
                "switch_role_link": switch_role_link,
            }
            results.append(item)

    return results


@get.command()
@click.pass_context
def ocm_aws_infrastructure_access_switch_role_links_flat(ctx):
    results = ocm_aws_infrastructure_access_switch_role_links_data()
    columns = ["cluster", "user_arn", "access_level", "switch_role_link"]
    print_output(ctx.obj["options"], results, columns)


@get.command()
@click.pass_context
def ocm_aws_infrastructure_access_switch_role_links(ctx):
    if ctx.obj["options"]["output"] != "md":
        raise Exception(f"Unupported output: {ctx.obj['options']['output']}")
    results = ocm_aws_infrastructure_access_switch_role_links_data()
    by_user = {}
    for r in results:
        by_user.setdefault(r["user"], []).append(r)
    columns = ["cluster", "source_login", "access_level", "switch_role_link"]
    for user in sorted(by_user.keys()):
        print(f"- [{user}](#{user})")
    for user in sorted(by_user.keys()):
        print("")
        print(f"# {user}")
        print_output(ctx.obj["options"], by_user[user], columns)


@get.command()
@click.pass_context
def clusters_egress_ips(ctx):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [
        c
        for c in clusters
        if c.get("ocm") is not None
        and c.get("awsInfrastructureManagementAccounts") is not None
    ]
    ocm_map = OCMMap(clusters=clusters, settings=settings)

    results = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        management_account = tfvpc._get_default_management_account(cluster)
        account = tfvpc._build_infrastructure_assume_role(
            management_account, cluster, ocm_map.get(cluster_name)
        )
        if not account:
            continue
        account["resourcesDefaultRegion"] = management_account["resourcesDefaultRegion"]
        aws_api = AWSApi(1, [account], settings=settings)
        egress_ips = aws_api.get_cluster_nat_gateways_egress_ips(account)
        item = {"cluster": cluster_name, "egress_ips": ", ".join(sorted(egress_ips))}
        results.append(item)

    columns = ["cluster", "egress_ips"]
    print_output(ctx.obj["options"], results, columns)


@get.command()
@click.pass_context
def clusters_aws_account_ids(ctx):
    settings = queries.get_app_interface_settings()
    clusters = [c for c in queries.get_clusters() if c.get("ocm") is not None]
    ocm_map = OCMMap(clusters=clusters, settings=settings)

    results = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        ocm = ocm_map.get(cluster_name)
        aws_account_id = ocm.get_cluster_aws_account_id(cluster_name)
        item = {
            "cluster": cluster_name,
            "aws_account_id": aws_account_id,
        }
        results.append(item)

    columns = ["cluster", "aws_account_id"]
    print_output(ctx.obj["options"], results, columns)


@get.command()
@click.pass_context
def terraform_users_credentials(ctx) -> None:
    accounts, working_dirs, _, aws_api = tfu.setup(False, 1)
    tf = Terraform(
        tfu.QONTRACT_INTEGRATION,
        tfu.QONTRACT_INTEGRATION_VERSION,
        tfu.QONTRACT_TF_PREFIX,
        accounts,
        working_dirs,
        10,
        aws_api,
        init_users=True,
    )
    credentials = []
    for account, output in tf.outputs.items():
        user_passwords = tf.format_output(output, tf.OUTPUT_TYPE_PASSWORDS)
        console_urls = tf.format_output(output, tf.OUTPUT_TYPE_CONSOLEURLS)
        for user_name, enc_password in user_passwords.items():
            item = {
                "account": account,
                "console_url": console_urls[account],
                "user_name": user_name,
                "encrypted_password": enc_password,
            }
            credentials.append(item)

    columns = ["account", "console_url", "user_name", "encrypted_password"]
    print_output(ctx.obj["options"], credentials, columns)


@get.command()
@click.pass_context
def aws_route53_zones(ctx):
    zones = queries.get_dns_zones()

    results = []
    for zone in zones:
        zone_name = zone["name"]
        zone_records = zone["records"]
        zone_nameservers = dnsutils.get_nameservers(zone_name)
        item = {
            "domain": zone_name,
            "records": len(zone_records),
            "nameservers": zone_nameservers,
        }
        results.append(item)

    columns = ["domain", "records", "nameservers"]
    print_output(ctx.obj["options"], results, columns)


@get.command()
@click.argument("cluster_name")
@click.pass_context
def bot_login(ctx, cluster_name):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c["name"] == cluster_name]
    if len(clusters) == 0:
        print(f"{cluster_name} not found.")
        sys.exit(1)

    cluster = clusters[0]
    server = cluster["serverUrl"]
    token = secret_reader.read(cluster["automationToken"])
    print(f"oc login --server {server} --token {token}")


@get.command(
    short_help="obtain automation credentials for ocm organization by org name"
)
@click.argument("org_name")
@click.pass_context
def ocm_login(ctx, org_name):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    ocms = [
        o for o in queries.get_openshift_cluster_managers() if o["name"] == org_name
    ]
    try:
        ocm = ocms[0]
    except IndexError:
        print(f"{org_name} not found.")
        sys.exit(1)

    client_secret = secret_reader.read(ocm["accessTokenClientSecret"])
    access_token_command = f'curl -s -X POST {ocm["accessTokenUrl"]} -d "grant_type=client_credentials" -d "client_id={ocm["accessTokenClientId"]}" -d "client_secret={client_secret}" | jq -r .access_token'
    print(f'ocm login --url {ocm["url"]} --token $({access_token_command})')


@get.command(
    short_help="obtain automation credentials for "
    "aws account by name. executing this "
    "command will set up the environment: "
    "$(aws get aws-creds --account-name foo)"
)
@click.argument("account_name")
@click.pass_context
def aws_creds(ctx, account_name):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    accounts = queries.get_aws_accounts(name=account_name)
    if not accounts:
        print(f"{account_name} not found.")
        sys.exit(1)

    account = accounts[0]
    secret = secret_reader.read_all(account["automationToken"])
    print(f"export AWS_REGION={account['resourcesDefaultRegion']}")
    print(f"export AWS_ACCESS_KEY_ID={secret['aws_access_key_id']}")
    print(f"export AWS_SECRET_ACCESS_KEY={secret['aws_secret_access_key']}")


@get.command(
    short_help="obtain sshuttle command for "
    "connecting to private clusters via a jump host. "
    "executing this command will set up the tunnel: "
    "$(qontract-cli get sshuttle-command bastion.example.com)"
)
@click.argument("jumphost_hostname", required=False)
@click.argument("cluster_name", required=False)
@click.pass_context
def sshuttle_command(
    ctx, jumphost_hostname: Optional[str], cluster_name: Optional[str]
):
    jumphosts_query_data = queries.get_jumphosts(hostname=jumphost_hostname)
    jumphosts = jumphosts_query_data.jumphosts or []
    for jh in jumphosts:
        jh_clusters = jh.clusters or []
        if cluster_name:
            jh_clusters = [c for c in jh_clusters if c.name == cluster_name]

        vpc_cidr_blocks = [c.network.vpc for c in jh_clusters if c.network]
        cmd = f"sshuttle -r {jh.hostname} {' '.join(vpc_cidr_blocks)}"
        print(cmd)


@get.command(
    short_help="obtain vault secrets for "
    "jenkins job by instance and name. executing this "
    "command will set up the environment: "
    "$(qontract-cli get jenkins-job-vault-secrets --instance-name ci --job-name job)"
)
@click.argument("instance_name")
@click.argument("job_name")
@click.pass_context
def jenkins_job_vault_secrets(ctx, instance_name, job_name):
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    jjb: JJB = init_jjb(secret_reader, instance_name, config_name=None, print_only=True)
    jobs = jjb.get_all_jobs([job_name], instance_name)[instance_name]
    if not jobs:
        print(f"{instance_name}/{job_name} not found.")
        sys.exit(1)
    job = jobs[0]
    for w in job["wrappers"]:
        vault_secrets = w.get("vault-secrets")
        if vault_secrets:
            vault_url = vault_secrets.get("vault-url")
            secrets = vault_secrets.get("secrets")
            for s in secrets:
                secret_path = s["secret-path"]
                secret_values = s["secret-values"]
                for sv in secret_values:
                    print(
                        f"export {sv['env-var']}=\"$(vault read -address={vault_url} -field={sv['vault-key']} {secret_path})\""
                    )


@get.command()
@click.argument("name", default="")
@click.pass_context
def namespaces(ctx, name):
    namespaces = queries.get_namespaces()
    if name:
        namespaces = [ns for ns in namespaces if ns["name"] == name]

    columns = ["name", "cluster.name", "app.name"]
    # TODO(mafriedm): fix this
    # do not sort
    ctx.obj["options"]["sort"] = False
    print_output(ctx.obj["options"], namespaces, columns)


def add_resource(item, resource, columns):
    provider = resource["provider"]
    if provider not in columns:
        columns.append(provider)
    item.setdefault(provider, 0)
    item[provider] += 1
    item["total"] += 1


@get.command
@click.pass_context
def cluster_openshift_resources(ctx):
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(orb.NAMESPACES_QUERY)["namespaces"]
    columns = ["name", "total"]
    results = {}
    for ns_info in namespaces:
        cluster_name = ns_info["cluster"]["name"]
        item = {"name": cluster_name, "total": 0}
        item = results.setdefault(cluster_name, item)
        total = {"name": "total", "total": 0}
        total = results.setdefault("total", total)
        ob.aggregate_shared_resources(ns_info, "openshiftResources")
        openshift_resources = ns_info.get("openshiftResources") or []
        for r in openshift_resources:
            add_resource(item, r, columns)
            add_resource(total, r, columns)

    # TODO(mafriedm): fix this
    # do not sort
    ctx.obj["options"]["sort"] = False
    print_output(ctx.obj["options"], results.values(), columns)


@get.command
@click.pass_context
def aws_terraform_resources(ctx):
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(tfr.TF_NAMESPACES_QUERY)["namespaces"]
    columns = ["name", "total"]
    results = {}
    for ns_info in namespaces:
        specs = (
            get_external_resource_specs(ns_info, provision_provider=PROVIDER_AWS) or []
        )
        for spec in specs:
            account = spec.provisioner_name
            item = {"name": account, "total": 0}
            item = results.setdefault(account, item)
            total = {"name": "total", "total": 0}
            total = results.setdefault("total", total)
            add_resource(item, spec.resource, columns)
            add_resource(total, spec.resource, columns)

    # TODO(mafriedm): fix this
    # do not sort
    ctx.obj["options"]["sort"] = False
    print_output(ctx.obj["options"], results.values(), columns)


@get.command()
@click.pass_context
def products(ctx):
    products = queries.get_products()
    columns = ["name", "description"]
    print_output(ctx.obj["options"], products, columns)


@describe.command()
@click.argument("name")
@click.pass_context
def product(ctx, name):
    products = queries.get_products()
    products = [p for p in products if p["name"].lower() == name.lower()]
    if len(products) != 1:
        print(f"{name} error")
        sys.exit(1)

    product = products[0]
    environments = product["environments"]
    columns = ["name", "description"]
    print_output(ctx.obj["options"], environments, columns)


@get.command()
@click.pass_context
def environments(ctx):
    environments = queries.get_environments()
    columns = ["name", "description", "product.name"]
    # TODO(mafriedm): fix this
    # do not sort
    ctx.obj["options"]["sort"] = False
    print_output(ctx.obj["options"], environments, columns)


@describe.command()
@click.argument("name")
@click.pass_context
def environment(ctx, name):
    environments = queries.get_environments()
    environments = [e for e in environments if e["name"].lower() == name.lower()]
    if len(environments) != 1:
        print(f"{name} error")
        sys.exit(1)

    environment = environments[0]
    namespaces = environment["namespaces"]
    columns = ["name", "cluster.name", "app.name"]
    # TODO(mafriedm): fix this
    # do not sort
    ctx.obj["options"]["sort"] = False
    print_output(ctx.obj["options"], namespaces, columns)


@get.command()
@click.pass_context
def services(ctx):
    apps = queries.get_apps()
    columns = ["name", "path", "onboardingStatus"]
    print_output(ctx.obj["options"], apps, columns)


@get.command()
@click.pass_context
def repos(ctx):
    repos = queries.get_repos()
    repos = [{"url": r} for r in repos]
    columns = ["url"]
    print_output(ctx.obj["options"], repos, columns)


@get.command()
@click.argument("org_username")
@click.pass_context
def roles(ctx, org_username):
    users = queries.get_roles()
    users = [u for u in users if u["org_username"] == org_username]

    if len(users) == 0:
        print("User not found")
        return

    user = users[0]

    roles = []

    def add(d):
        for i, r in enumerate(roles):
            if all(d[k] == r[k] for k in ("type", "name", "resource")):
                roles.insert(
                    i + 1, {"type": "", "name": "", "resource": "", "ref": d["ref"]}
                )
                return

        roles.append(d)

    for role in user["roles"]:
        role_name = role["path"]

        for p in role.get("permissions") or []:
            r_name = p["service"]

            if "org" in p or "team" in p:
                r_name = r_name.split("-")[0]

            if "org" in p:
                r_name += "/" + p["org"]

            if "team" in p:
                r_name += "/" + p["team"]

            add(
                {
                    "type": "permission",
                    "name": p["name"],
                    "resource": r_name,
                    "ref": role_name,
                }
            )

        for aws in role.get("aws_groups") or []:
            for policy in aws["policies"]:
                add(
                    {
                        "type": "aws",
                        "name": policy,
                        "resource": aws["account"]["name"],
                        "ref": aws["path"],
                    }
                )

        for a in role.get("access") or []:
            if a["cluster"]:
                cluster_name = a["cluster"]["name"]
                add(
                    {
                        "type": "cluster",
                        "name": a["clusterRole"],
                        "resource": cluster_name,
                        "ref": role_name,
                    }
                )
            elif a["namespace"]:
                ns_name = a["namespace"]["name"]
                add(
                    {
                        "type": "namespace",
                        "name": a["role"],
                        "resource": ns_name,
                        "ref": role_name,
                    }
                )

        for s in role.get("self_service") or []:
            for d in s.get("datafiles") or []:
                name = d.get("name")
                if name:
                    add(
                        {
                            "type": "saas_file",
                            "name": "owner",
                            "resource": name,
                            "ref": role_name,
                        }
                    )

    columns = ["type", "name", "resource", "ref"]
    print_output(ctx.obj["options"], roles, columns)


@get.command()
@click.argument("org_username", default="")
@click.pass_context
def users(ctx, org_username):
    users = queries.get_users()
    if org_username:
        users = [u for u in users if u["org_username"] == org_username]

    columns = ["org_username", "github_username", "name"]
    print_output(ctx.obj["options"], users, columns)


@get.command()
@click.pass_context
def integrations(ctx):
    environments = queries.get_integrations()
    columns = ["name", "description"]
    print_output(ctx.obj["options"], environments, columns)


@get.command()
@click.pass_context
def quay_mirrors(ctx):
    apps = queries.get_quay_repos()

    mirrors = []
    for app in apps:
        quay_repos = app["quayRepos"]

        if quay_repos is None:
            continue

        for qr in quay_repos:
            org_name = qr["org"]["name"]
            for item in qr["items"]:
                mirror = item["mirror"]

                if mirror is None:
                    continue

                name = item["name"]
                url = item["mirror"]["url"]
                public = item["public"]

                mirrors.append(
                    {
                        "repo": f"quay.io/{org_name}/{name}",
                        "public": public,
                        "upstream": url,
                    }
                )

    columns = ["repo", "upstream", "public"]
    print_output(ctx.obj["options"], mirrors, columns)


@get.command()
@click.argument("cluster")
@click.argument("namespace")
@click.argument("kind")
@click.argument("name")
@click.pass_context
def root_owner(ctx, cluster, namespace, kind, name):
    settings = queries.get_app_interface_settings()
    clusters = [c for c in queries.get_clusters(minimal=True) if c["name"] == cluster]
    oc_map = OC_Map(
        clusters=clusters,
        integration="qontract-cli",
        thread_pool_size=1,
        settings=settings,
        init_api_resources=True,
    )
    oc = oc_map.get(cluster)
    obj = oc.get(namespace, kind, name)
    root_owner = oc.get_obj_root_owner(
        namespace, obj, allow_not_found=True, allow_not_controller=True
    )

    # TODO(mafriedm): fix this
    # do not sort
    ctx.obj["options"]["sort"] = False
    # a bit hacky, but ¯\_(ツ)_/¯
    if ctx.obj["options"]["output"] != "json":
        ctx.obj["options"]["output"] = "yaml"

    print_output(ctx.obj["options"], root_owner)


@get.command()
@click.argument("aws_account")
@click.argument("identifier")
@click.pass_context
def service_owners_for_rds_instance(ctx, aws_account, identifier):
    namespaces = queries.get_namespaces()
    service_owners = []
    for namespace_info in namespaces:
        if not managed_external_resources(namespace_info):
            continue

        for spec in get_external_resource_specs(namespace_info):
            if (
                spec.provider == "rds"
                and spec.provisioner_name == aws_account
                and spec.identifier == identifier
            ):
                service_owners = namespace_info["app"]["serviceOwners"]
                break

    columns = ["name", "email"]
    print_output(ctx.obj["options"], service_owners, columns)


@get.command()
@click.pass_context
def sre_checkpoints(ctx):
    apps = queries.get_apps()

    parent_apps = {app["parentApp"]["path"] for app in apps if app.get("parentApp")}

    latest_sre_checkpoints = get_latest_sre_checkpoints()

    checkpoints_data = [
        {
            "name": full_name(app),
            "latest": latest_sre_checkpoints.get(full_name(app), ""),
        }
        for app in apps
        if (app["path"] not in parent_apps and app["onboardingStatus"] == "OnBoarded")
    ]

    checkpoints_data.sort(key=lambda c: c["latest"], reverse=True)

    columns = ["name", "latest"]
    print_output(ctx.obj["options"], checkpoints_data, columns)


@get.command()
@click.pass_context
def app_interface_merge_queue(ctx):
    settings = queries.get_app_interface_settings()
    instance = queries.get_gitlab_instance()
    gl = GitLabApi(instance, project_url=settings["repoUrl"], settings=settings)
    merge_requests = glhk.get_merge_requests(True, gl)

    columns = [
        "id",
        "title",
        "label_priority",
        "approved_at",
        "approved_span_minutes",
        "approved_by",
        "labels",
    ]
    merge_queue_data = []
    now = datetime.utcnow()
    for mr in merge_requests:
        item = {
            "id": f"[{mr['mr'].iid}]({mr['mr'].web_url})",
            "title": mr["mr"].title,
            "label_priority": mr["label_priority"]
            + 1,  # adding 1 for human readability
            "approved_at": mr["approved_at"],
            "approved_span_minutes": (
                now - datetime.strptime(mr["approved_at"], glhk.DATE_FORMAT)
            ).total_seconds()
            / 60,
            "approved_by": mr["approved_by"],
            "labels": ", ".join(mr["labels"]),
        }
        merge_queue_data.append(item)

    ctx.obj["options"]["sort"] = False  # do not sort
    print_output(ctx.obj["options"], merge_queue_data, columns)


@get.command()
@click.pass_context
def app_interface_review_queue(ctx):
    settings = queries.get_app_interface_settings()
    instance = queries.get_gitlab_instance()
    secret_reader = SecretReader(settings=settings)
    jjb: JJB = init_jjb(secret_reader)
    columns = [
        "id",
        "repo",
        "title",
        "onboarding",
        "author",
        "updated_at",
        "labels",
    ]

    def get_mrs(repo, url) -> list[dict[str, str]]:
        gl = GitLabApi(instance, project_url=url, settings=settings)
        merge_requests = gl.get_merge_requests(state=MRState.OPENED)
        job = jjb.get_job_by_repo_url(url, job_type="gl-pr-check")
        trigger_phrases_regex = jjb.get_trigger_phrases_regex(job)

        queue_data = []
        for mr in merge_requests:
            if mr.work_in_progress:
                continue
            if len(mr.commits()) == 0:
                continue
            if mr.merge_status in [
                MRStatus.CANNOT_BE_MERGED,
                MRStatus.CANNOT_BE_MERGED_RECHECK,
            ]:
                continue

            labels = mr.attributes.get("labels")
            if glhk.is_good_to_merge(labels):
                continue
            if "stale" in labels:
                continue
            if SAAS_FILE_UPDATE in labels:
                continue
            if SELF_SERVICEABLE in labels:
                continue

            pipelines = mr.pipelines()
            if not pipelines:
                continue
            running_pipelines = [p for p in pipelines if p["status"] == "running"]
            if running_pipelines:
                continue
            last_pipeline_result = pipelines[0]["status"]
            if last_pipeline_result != "success":
                continue

            author = mr.author["username"]
            app_sre_team_members = [u.username for u in gl.get_app_sre_group_users()]
            if author in app_sre_team_members:
                continue

            is_assigned_by_app_sre = gl.is_assigned_by_team(mr, app_sre_team_members)
            if is_assigned_by_app_sre:
                continue

            is_last_action_by_app_sre = gl.is_last_action_by_team(
                mr, app_sre_team_members, glhk.HOLD_LABELS
            )

            if is_last_action_by_app_sre:
                last_comment = gl.last_comment(mr, exclude_bot=True)
                # skip only if the last comment isn't a trigger phrase
                if (
                    last_comment
                    and trigger_phrases_regex
                    and not re.fullmatch(trigger_phrases_regex, last_comment["body"])
                ):
                    continue

            item = {
                "id": f"[{mr.iid}]({mr.web_url})",
                "repo": repo,
                "title": mr.title,
                "onboarding": "onboarding" in labels,
                "updated_at": mr.updated_at,
                "author": author,
                "labels": ", ".join(labels),
            }
            queue_data.append(item)
        return queue_data

    queue_data = []

    for repo in queries.get_review_repos():
        queue_data.extend(get_mrs(repo["name"], repo["url"]))

    queue_data.sort(key=itemgetter("updated_at"))
    ctx.obj["options"]["sort"] = False  # do not sort
    print_output(ctx.obj["options"], queue_data, columns)


@get.command()
@click.pass_context
def app_interface_open_selfserviceable_mr_queue(ctx):
    settings = queries.get_app_interface_settings()
    instance = queries.get_gitlab_instance()
    gl = GitLabApi(instance, project_url=settings["repoUrl"], settings=settings)
    merge_requests = gl.get_merge_requests(state=MRState.OPENED)

    columns = [
        "id",
        "title",
        "author",
        "updated_at",
        "labels",
    ]
    queue_data = []
    for mr in merge_requests:
        if mr.work_in_progress:
            continue
        if len(mr.commits()) == 0:
            continue

        # skip stale or non self serviceable MRs
        labels = mr.attributes.get("labels")
        if "stale" in labels:
            continue
        if SELF_SERVICEABLE not in labels and SAAS_FILE_UPDATE not in labels:
            continue

        # skip MRs where AppSRE is involved already (author or assignee)
        author = mr.author["username"]
        app_sre_team_members = [u.username for u in gl.get_app_sre_group_users()]
        if author in app_sre_team_members:
            continue
        is_assigned_by_app_sre = gl.is_assigned_by_team(mr, app_sre_team_members)
        if is_assigned_by_app_sre:
            continue

        # skip MRs where the pipeline is still running or where it failed
        pipelines = mr.pipelines()
        if not pipelines:
            continue
        running_pipelines = [p for p in pipelines if p["status"] == "running"]
        if running_pipelines:
            continue
        last_pipeline_result = pipelines[0]["status"]
        if last_pipeline_result != "success":
            continue

        item = {
            "id": f"[{mr.iid}]({mr.web_url})",
            "title": mr.title,
            "updated_at": mr.updated_at,
            "author": author,
            "labels": ", ".join(labels),
        }
        queue_data.append(item)

    queue_data.sort(key=itemgetter("updated_at"))
    ctx.obj["options"]["sort"] = False  # do not sort
    print_output(ctx.obj["options"], queue_data, columns)


@get.command()
@click.pass_context
def change_types(ctx):
    """List all change types."""
    change_types = fetch_change_type_processors(gql.get_api())

    usage_statistics: dict[str, int] = defaultdict(int)
    roles = fetch_self_service_roles(gql.get_api())
    for r in roles:
        for ss in r.self_service:
            nr_files = len(ss.datafiles or []) + len(ss.resources or [])
            usage_statistics[ss.change_type.name] += nr_files
    data = []
    for ct in change_types:
        data.append(
            {
                "name": ct.name,
                "description": ct.description,
                "applicable to": f"{ct.context_type.value} {ct.context_schema or '' }",
                "# usages": usage_statistics[ct.name],
            }
        )
    columns = ["name", "description", "applicable to", "# usages"]
    print_output(ctx.obj["options"], data, columns)


@get.command()
@click.pass_context
def app_interface_merge_history(ctx):
    settings = queries.get_app_interface_settings()
    instance = queries.get_gitlab_instance()
    gl = GitLabApi(instance, project_url=settings["repoUrl"], settings=settings)
    merge_requests = gl.project.mergerequests.list(state=MRState.MERGED, per_page=100)

    columns = [
        "id",
        "title",
        "merged_at",
        "labels",
    ]
    merge_queue_data = []
    for mr in merge_requests:
        item = {
            "id": f"[{mr.iid}]({mr.web_url})",
            "title": mr.title,
            "merged_at": mr.merged_at,
            "labels": ", ".join(mr.attributes.get("labels")),
        }
        merge_queue_data.append(item)

    merge_queue_data.sort(key=itemgetter("merged_at"), reverse=True)
    ctx.obj["options"]["sort"] = False  # do not sort
    print_output(ctx.obj["options"], merge_queue_data, columns)


@root.group()
@output
@click.pass_context
def set(ctx, output):
    ctx.obj["output"] = output


@set.command()
@click.argument("workspace")
@click.argument("usergroup")
@click.argument("username")
@click.pass_context
def slack_usergroup(ctx, workspace, usergroup, username):
    """Update users in a slack usergroup.
    Use an org_username as the username.
    To empty a slack usergroup, pass '' (empty string) as the username.
    """
    settings = queries.get_app_interface_settings()
    slack = slackapi_from_queries("qontract-cli")
    ugid = slack.get_usergroup_id(usergroup)
    if username:
        mail_address = settings["smtp"]["mailAddress"]
        users = [slack.get_user_id_by_name(username, mail_address)]
    else:
        users = [slack.get_random_deleted_user()]
    slack.update_usergroup_users(ugid, users)


@root.group()
@environ(["APP_INTERFACE_STATE_BUCKET", "APP_INTERFACE_STATE_BUCKET_ACCOUNT"])
@click.pass_context
def state(ctx):
    pass


@state.command()
@click.argument("integration", default="")
@click.pass_context
def ls(ctx, integration):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(integration, accounts, settings=settings)
    keys = state.ls()
    # if integration in not defined the 2th token will be the integration name
    key_index = 1 if integration else 2
    table_content = [
        {
            "integration": integration or k.split("/")[1],
            "key": "/".join(k.split("/")[key_index:]),
        }
        for k in keys
    ]
    print_output(
        {"output": "table", "sort": False}, table_content, ["integration", "key"]
    )


@state.command()  # type: ignore
@click.argument("integration")
@click.argument("key")
@click.pass_context
def get(ctx, integration, key):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(integration, accounts, settings=settings)
    value = state.get(key)
    print(value)


@state.command()
@click.argument("integration")
@click.argument("key")
@click.pass_context
def add(ctx, integration, key):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(integration, accounts, settings=settings)
    state.add(key)


@state.command()  # type: ignore
@click.argument("integration")
@click.argument("key")
@click.argument("value")
@click.pass_context
def set(ctx, integration, key, value):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(integration, accounts, settings=settings)
    state.add(key, value=value, force=True)


@state.command()
@click.argument("integration")
@click.argument("key")
@click.pass_context
def rm(ctx, integration, key):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(integration, accounts, settings=settings)
    state.rm(key)


@root.command()
@click.argument("cluster")
@click.argument("namespace")
@click.argument("kind")
@click.argument("name")
@click.option(
    "-p",
    "--path",
    help="Only show templates that match with the given path.",
)
@click.option(
    "-s",
    "--secret-reader",
    default="vault",
    help="Location to read secrets.",
    type=click.Choice(["config", "vault"]),
)
@click.pass_context
def template(ctx, cluster, namespace, kind, name, path, secret_reader):
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(orb.NAMESPACES_QUERY)["namespaces"]
    namespace_info = [
        n
        for n in namespaces
        if n["cluster"]["name"] == cluster and n["name"] == namespace
    ]
    if len(namespace_info) != 1:
        print(f"{cluster}/{namespace} error")
        sys.exit(1)

    settings = queries.get_app_interface_settings()
    settings["vault"] = secret_reader == "vault"

    if path.startswith("resources"):
        path = path.replace("resources", "", 1)

    [namespace_info] = namespace_info
    openshift_resources = namespace_info.get("openshiftResources")
    for r in openshift_resources:
        resource_path = r.get("resource", {}).get("path")
        if path and path != resource_path:
            continue
        openshift_resource = orb.fetch_openshift_resource(r, namespace_info, settings)
        if openshift_resource.kind.lower() != kind.lower():
            continue
        if openshift_resource.name != name:
            continue
        print_output({"output": "yaml", "sort": False}, openshift_resource.body)
        break


@root.command()
@click.argument("path")
@click.argument("cluster")
@click.option(
    "-n",
    "--namespace",
    default="openshift-customer-monitoring",
    help="Cluster namespace where the rules are deployed. It defaults to "
    "openshift-customer-monitoring.",
)
@click.option(
    "-s",
    "--secret-reader",
    default="vault",
    help="Location to read secrets.",
    type=click.Choice(["config", "vault"]),
)
@click.pass_context
def run_prometheus_test(ctx, path, cluster, namespace, secret_reader):
    """Run prometheus tests in PATH loading associated rules from CLUSTER."""
    gqlapi = gql.get_api()

    if path.startswith("resources"):
        path = path.replace("resources", "", 1)

    try:
        resource = gqlapi.get_resource(path)
    except gql.GqlGetResourceError as e:
        print(f"Error in provided PATH: {e}.")
        sys.exit(1)

    test = resource["content"]
    data = get_data_from_jinja_test_template(test, ["rule_files", "target_clusters"])
    target_clusters = data["target_clusters"]
    if len(target_clusters) > 0 and cluster not in target_clusters:
        print(
            f"Skipping test: {path}, cluster {cluster} not in target_clusters {target_clusters}"
        )
    rule_files = data["rule_files"]
    if not rule_files:
        print(f"Cannot parse test in {path}.")
        sys.exit(1)

    if len(rule_files) > 1:
        print("Only 1 rule file per test")
        sys.exit(1)

    rule_file_path = rule_files[0]

    namespace_info = [
        n
        for n in gqlapi.query(orb.NAMESPACES_QUERY)["namespaces"]
        if n["cluster"]["name"] == cluster and n["name"] == namespace
    ]
    if len(namespace_info) != 1:
        print(f"{cluster}/{namespace} does not exist.")
        sys.exit(1)

    settings = queries.get_app_interface_settings()
    settings["vault"] = secret_reader == "vault"

    ni = namespace_info[0]
    ob.aggregate_shared_resources(ni, "openshiftResources")
    openshift_resources = ni.get("openshiftResources")
    rule_spec = {}
    for r in openshift_resources:
        resource_path = r.get("resource", {}).get("path")
        if resource_path != rule_file_path:
            continue

        if "add_path_to_prom_rules" not in r:
            r["add_path_to_prom_rules"] = False

        openshift_resource = orb.fetch_openshift_resource(r, ni, settings)
        if openshift_resource.kind.lower() != "prometheusrule":
            print(f"Object in {rule_file_path} is not a PrometheusRule.")
            sys.exit(1)

        rule_spec = openshift_resource.body["spec"]
        variables = json.loads(r.get("variables") or "{}")
        variables["resource"] = r
        break

    if not rule_spec:
        print(
            f"Rules file referenced in {path} does not exist in namespace "
            f"{namespace} from cluster {cluster}."
        )
        sys.exit(1)

    test_yaml_spec = yaml.safe_load(
        orb.process_extracurlyjinja2_template(
            body=test, vars=variables, settings=settings
        )
    )
    test_yaml_spec.pop("$schema")

    result = promtool.run_test(
        test_yaml_spec=test_yaml_spec, rule_files={rule_file_path: rule_spec}
    )

    print(result.message, end="")

    if not result:
        sys.exit(1)


@root.command()
@click.argument("cluster")
@click.argument("namespace")
@click.argument("rules_path")
@click.option(
    "-a",
    "--alert-name",
    help="Alert name in RULES_PATH. Receivers for all alerts will be returned if not "
    "specified.",
)
@click.option(
    "-c",
    "--alertmanager-secret-path",
    default="/observability/alertmanager/alertmanager-instance.secret.yaml",
    help="Alert manager secret path.",
)
@click.option(
    "-n",
    "--alertmanager-namespace",
    default="openshift-customer-monitoring",
    help="Alertmanager namespace.",
)
@click.option(
    "-k",
    "--alertmanager-secret-key",
    default="alertmanager.yaml",
    help="Alertmanager config key in secret.",
)
@click.option(
    "-s",
    "--secret-reader",
    default="vault",
    help="Location to read secrets.",
    type=click.Choice(["config", "vault"]),
)
@click.option(
    "-l",
    "--additional-label",
    help="Additional label in key=value format. It can be specified multiple times. If "
    "the same label is defined in the alert, the additional label will have "
    "precedence.",
    multiple=True,
)
@click.pass_context
def alert_to_receiver(
    ctx,
    cluster,
    namespace,
    rules_path,
    alert_name,
    alertmanager_secret_path,
    alertmanager_namespace,
    alertmanager_secret_key,
    secret_reader,
    additional_label,
):

    additional_labels = {}
    for al in additional_label:
        try:
            key, value = al.split("=")
        except ValueError:
            print(f"Additional label {al} not passed using key=value format")
            sys.exit(1)

        if not key or not value:
            print(f"Additional label {al} not passed using key=value format")
            sys.exit(1)

        additional_labels[key] = value

    gqlapi = gql.get_api()
    namespaces = gqlapi.query(orb.NAMESPACES_QUERY)["namespaces"]
    cluster_namespaces = [n for n in namespaces if n["cluster"]["name"] == cluster]

    if len(cluster_namespaces) == 0:
        print(f"Unknown cluster {cluster}")
        sys.exit(1)

    settings = queries.get_app_interface_settings()
    if secret_reader == "config":
        settings["vault"] = False
    else:
        settings["vault"] = True

    # Get alertmanager config
    am_config = ""
    for ni in cluster_namespaces:
        if ni["name"] != alertmanager_namespace:
            continue
        ob.aggregate_shared_resources(ni, "openshiftResources")
        for r in ni.get("openshiftResources"):
            if r.get("resource", {}).get("path") != alertmanager_secret_path:
                continue
            openshift_resource = orb.fetch_openshift_resource(r, ni, settings)
            body = openshift_resource.body
            if "data" in body:
                am_config = base64.b64decode(
                    body["data"][alertmanager_secret_key]
                ).decode("utf-8")
            elif "stringData" in body:
                am_config = body["stringData"][alertmanager_secret_key]
            else:
                print("Cannot get alertmanager configuration")
                sys.exit(1)
        break

    rule_spec = {}
    for ni in cluster_namespaces:
        if ni["name"] != namespace:
            continue
        for r in ni.get("openshiftResources"):
            if r.get("resource", {}).get("path") != rules_path:
                continue
            openshift_resource = orb.fetch_openshift_resource(r, ni, settings)
            if openshift_resource.kind.lower() != "prometheusrule":
                print(f"Object in {rules_path} is not a PrometheusRule")
                sys.exit(1)
            rule_spec = openshift_resource.body["spec"]

            break  # openshift resource
        break  # cluster_namespaces

    if not rule_spec:
        print(
            f"Cannot find any rule in {rules_path} from cluster {cluster} and "
            f"namespace {namespace}"
        )
        sys.exit(1)

    alert_labels: list[dict] = []
    for group in rule_spec["groups"]:
        for rule in group["rules"]:
            alert_labels.append(
                {
                    "name": rule["alert"],
                    "labels": rule["labels"] | additional_labels,
                }
            )

    if alert_name:
        alert_labels = [al for al in alert_labels if al["name"] == alert_name]

        if not alert_labels:
            print(f"Cannot find alert {alert_name} in rules {rules_path}")
            sys.exit(1)

    for al in alert_labels:
        result = amtool.config_routes_test(am_config, al["labels"])
        if not result:
            print(f"Error running amtool: {result}")
            sys.exit(1)
        print("|".join([al["name"], str(result)]))


@root.command()
@click.option("--app-name", default=None, help="app to act on.")
@click.option("--saas-file-name", default=None, help="saas-file to act on.")
@click.option("--env-name", default=None, help="environment to use for parameters.")
@click.pass_context
def saas_dev(ctx, app_name=None, saas_file_name=None, env_name=None):
    if env_name in [None, ""]:
        print("env-name must be defined")
        return
    saas_files = queries.get_saas_files(saas_file_name, env_name, app_name)
    if not saas_files:
        print("no saas files found")
        sys.exit(1)
    for saas_file in saas_files:
        saas_file_parameters = json.loads(saas_file.get("parameters") or "{}")
        for rt in saas_file["resourceTemplates"]:
            url = rt["url"]
            path = rt["path"]
            rt_parameters = json.loads(rt.get("parameters") or "{}")
            for target in rt["targets"]:
                target_parameters = json.loads(target.get("parameters") or "{}")
                namespace = target["namespace"]
                namespace_name = namespace["name"]
                environment = namespace["environment"]
                if environment["name"] != env_name:
                    continue
                ref = target["ref"]
                environment_parameters = json.loads(
                    environment.get("parameters") or "{}"
                )
                parameters = {}
                parameters.update(environment_parameters)
                parameters.update(saas_file_parameters)
                parameters.update(rt_parameters)
                parameters.update(target_parameters)

                for replace_key, replace_value in parameters.items():
                    if not isinstance(replace_value, str):
                        continue
                    replace_pattern = "${" + replace_key + "}"
                    for k, v in parameters.items():
                        if not isinstance(v, str):
                            continue
                        if replace_pattern in v:
                            parameters[k] = v.replace(replace_pattern, replace_value)

                parameters_cmd = ""
                for k, v in parameters.items():
                    parameters_cmd += f' -p {k}="{v}"'
                raw_url = url.replace("github.com", "raw.githubusercontent.com")
                if "gitlab" in raw_url:
                    raw_url += "/raw"
                raw_url += "/" + ref
                raw_url += path
                cmd = (
                    "oc process --local --ignore-unknown-parameters"
                    + f"{parameters_cmd} -f {raw_url}"
                    + f" | oc apply -n {namespace_name} -f - --dry-run"
                )
                print(cmd)


@root.command()
@click.argument("query")
@click.option(
    "--output",
    "-o",
    help="output type",
    default="json",
    type=click.Choice(["json", "yaml"]),
)
def query(output, query):
    """Run a raw GraphQL query"""
    gqlapi = gql.get_api()
    result = gqlapi.query(query)

    if output == "yaml":
        print(yaml.safe_dump(result))
    elif output == "json":
        print(json.dumps(result))


@root.command()
@click.argument("cluster")
@click.argument("query")
def promquery(cluster, query):
    """Run a PromQL query"""
    config_data = config.get_config()
    auth = {"path": config_data["promql-auth"]["secret_path"], "field": "token"}
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    prom_auth_creds = secret_reader.read(auth)
    prom_auth = requests.auth.HTTPBasicAuth(*prom_auth_creds.split(":"))

    url = f"https://prometheus.{cluster}.devshift.net/api/v1/query"

    response = requests.get(url, params={"query": query}, auth=prom_auth, timeout=60)
    response.raise_for_status()

    print(json.dumps(response.json(), indent=4))


@root.command()
@click.option(
    "--app-path",
    help="Path in app-interface of the app.yml being reviewed (ex. /services/$APP_NAME/app.yml",
)
@click.option(
    "--parent-ticket",
    help="JIRA ticket to link all found issues to (ex. APPSRE-NNNN)",
    default=None,
)
@click.option(
    "--jiraboard",
    help="JIRA board where to send any new tickets. If not "
    "provided, the folder found in the application's escalation "
    "policy will be used. (ex. APPSRE)",
    default=None,
)
@click.option(
    "--jiradef",
    help="Path to the JIRA server's definition in app-interface ("
    "ex. /teams/$TEAM_NAME/jira/$JIRA_FILE.yaml",
    default=None,
)
@click.option(
    "--create-parent-ticket/--no-create-parent-ticket",
    help="Whether to create a parent ticket if none was provided",
    default=False,
)
@click.option(
    "--dry-run/--no-dry-run",
    help="Do not/do create tickets for failed checks",
    default=False,
)
def sre_checkpoint_metadata(
    app_path, parent_ticket, jiraboard, jiradef, create_parent_ticket, dry_run
):
    """Check an app path for checkpoint-related metadata."""
    data = queries.get_app_metadata(app_path)
    settings = queries.get_app_interface_settings()
    app = data[0]

    if jiradef:
        assert jiraboard
        board_info = queries.get_simple_jira_boards(jiradef)
    else:
        board_info = app["escalationPolicy"]["channels"]["jiraBoard"]
    board_info = board_info[0]
    # Overrides for easier testing
    if jiraboard:
        board_info["name"] = jiraboard
    report_invalid_metadata(app, app_path, board_info, settings, parent_ticket, dry_run)


@root.command()
@click.option("--vault-path", help="Path to the secret in vault")
@click.option(
    "--vault-secret-version",
    help="Optionally also specify the secret's version",
    default=-1,
)
@click.option("--file-path", help="Local file path to the secret")
@click.option("--openshift-path", help="{cluster}/{namespace}/{secret}")
@click.option(
    "-o",
    "--output",
    help="File to print encrypted output to. If not set, prints to stdout.",
)
@click.option(
    "--for-user",
    help="OrgName of user whose gpg key will be used for encryption",
    default=None,
    required=True,
)
def gpg_encrypt(
    vault_path, vault_secret_version, file_path, openshift_path, output, for_user
):
    """
    Encrypt the specified secret (local file, vault or openshift) with a
    given users gpg key. This is intended for easily sharing secrets with
    customers in case of emergency. The command requires access to
    a running gql server.
    """
    return GPGEncryptCommand.create(
        command_data=GPGEncryptCommandData(
            vault_secret_path=vault_path,
            vault_secret_version=int(vault_secret_version),
            secret_file_path=file_path,
            openshift_path=openshift_path,
            output=output,
            target_user=for_user,
        ),
    ).execute()


@root.command()
@click.option("--change-type-name")
@click.option("--role-name")
@click.option(
    "--app-interface-path",
    help="filesystem path to a local app-interface repo",
    default=os.environ.get("APP_INTERFACE_PATH", None),
)
def test_change_type(change_type_name: str, role_name: str, app_interface_path: str):
    from reconcile.change_owners import tester

    # tester.test_change_type(change_type_name, datafile_path)
    tester.test_change_type_in_context(change_type_name, role_name, app_interface_path)


if __name__ == "__main__":
    root()  # pylint: disable=no-value-for-parameter
