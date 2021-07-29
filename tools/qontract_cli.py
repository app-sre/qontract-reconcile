import json
import sys

import click
import requests
import yaml

from tabulate import tabulate

import reconcile.utils.dnsutils as dnsutils
import reconcile.utils.gql as gql
import reconcile.utils.config as config
from reconcile.utils.secret_reader import SecretReader
import reconcile.queries as queries
import reconcile.openshift_resources_base as orb
import reconcile.terraform_users as tfu
import reconcile.terraform_vpc_peerings as tfvpc

from reconcile.utils.aws_api import AWSApi
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.state import State
from reconcile.utils.environ import environ
from reconcile.utils.ocm import OCMMap
from reconcile.cli import config_file

from tools.sre_checkpoints import full_name, get_latest_sre_checkpoints


def output(function):
    function = click.option('--output', '-o',
                            help='output type',
                            default='table',
                            type=click.Choice([
                                'table',
                                'md',
                                'json',
                                'yaml']))(function)
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
@click.pass_context
def get(ctx, output):
    ctx.obj['output'] = output


@root.group()
@output
@click.pass_context
def describe(ctx, output):
    ctx.obj['output'] = output


@get.command()
@click.pass_context
def settings(ctx):
    settings = queries.get_app_interface_settings()
    columns = ['vault', 'kubeBinary', 'mergeRequestGateway']
    print_output(ctx.obj['output'], [settings], columns)


@get.command()
@click.argument('name', default='')
@click.pass_context
def aws_accounts(ctx, name):
    accounts = queries.get_aws_accounts()
    if name:
        accounts = [a for a in accounts if a['name'] == name]

    columns = ['name', 'consoleUrl']
    print_output(ctx.obj['output'], accounts, columns)


@get.command()
@click.argument('name', default='')
@click.pass_context
def clusters(ctx, name):
    clusters = queries.get_clusters()
    if name:
        clusters = [c for c in clusters if c['name'] == name]

    columns = ['name', 'consoleUrl', 'kibanaUrl', 'prometheusUrl']
    print_output(ctx.obj['output'], clusters, columns)


@get.command()
@click.argument('name', default='')
@click.pass_context
def cluster_upgrades(ctx, name):
    settings = queries.get_app_interface_settings()

    clusters = queries.get_clusters()

    clusters_ocm = [c for c in clusters
                    if c.get('ocm') is not None and c.get('auth') is not None]

    ocm_map = OCMMap(clusters=clusters_ocm, settings=settings)

    clusters_data = []
    for c in clusters:
        if name and c['name'] != name:
            continue

        if not c.get('spec'):
            continue

        data = {
            'name': c['name'],
            'id': c['spec']['id'],
            'external_id': c['spec'].get('external_id'),
        }

        upgrade_policy = c['upgradePolicy']

        if upgrade_policy:
            data['upgradePolicy'] = upgrade_policy.get('schedule_type')

        if data.get('upgradePolicy') == 'automatic':
            data['schedule'] = c['upgradePolicy']['schedule']
            ocm = ocm_map.get(c['name'])
            if ocm:
                upgrade_policy = ocm.get_upgrade_policies(c['name'])
                if upgrade_policy and len(upgrade_policy) > 0:
                    next_run = upgrade_policy[0].get('next_run')
                    if next_run:
                        data['next_run'] = next_run
        else:
            data['upgradePolicy'] = 'manual'

        clusters_data.append(data)

    columns = ['name', 'upgradePolicy', 'schedule', 'next_run']

    print_output(ctx.obj['output'], clusters_data, columns)


@get.command()
@click.argument('name', default='')
@click.pass_context
def clusters_network(ctx, name):
    clusters = queries.get_clusters()
    if name:
        clusters = [c for c in clusters if c['name'] == name]

    columns = ['name', 'network.vpc', 'network.service', 'network.pod']
    print_output(ctx.obj['output'], clusters, columns)


@get.command()
@click.pass_context
def ocm_aws_infrastructure_access_switch_role_links(ctx):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('ocm') is not None]
    ocm_map = OCMMap(clusters=clusters, settings=settings)

    results = []
    for cluster in clusters:
        cluster_name = cluster['name']
        ocm = ocm_map.get(cluster_name)
        role_grants = \
            ocm.get_aws_infrastructure_access_role_grants(cluster_name)
        for user_arn, access_level, _, switch_role_link in role_grants:
            item = {
                'cluster': cluster_name,
                'user_arn': user_arn,
                'access_level': access_level,
                'switch_role_link': switch_role_link,
            }
            results.append(item)

    columns = ['cluster', 'user_arn', 'access_level', 'switch_role_link']
    print_output(ctx.obj['output'], results, columns)


@get.command()
@click.pass_context
def clusters_egress_ips(ctx):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters
                if c.get('ocm') is not None
                and c.get('awsInfrastructureAccess') is not None]
    ocm_map = OCMMap(clusters=clusters, settings=settings)

    results = []
    for cluster in clusters:
        cluster_name = cluster['name']
        account = tfvpc.aws_account_from_infrastructure_access(
            cluster,
            'network-mgmt',
            ocm_map
        )
        aws_api = AWSApi(1, [account], settings=settings)
        egress_ips = \
            aws_api.get_cluster_nat_gateways_egress_ips(account)
        item = {
            'cluster': cluster_name,
            'egress_ips': ', '.join(egress_ips)
        }
        results.append(item)

    columns = ['cluster', 'egress_ips']
    print_output(ctx.obj['output'], results, columns)


@get.command()
@click.pass_context
def terraform_users_credentials(ctx):
    accounts, working_dirs = tfu.setup(False, 1)
    tf = Terraform(tfu.QONTRACT_INTEGRATION,
                   tfu.QONTRACT_INTEGRATION_VERSION,
                   tfu.QONTRACT_TF_PREFIX,
                   accounts,
                   working_dirs,
                   10,
                   init_users=True)
    credentials = []
    for account, output in tf.outputs.items():
        user_passwords = tf.format_output(
            output, tf.OUTPUT_TYPE_PASSWORDS)
        console_urls = tf.format_output(
            output, tf.OUTPUT_TYPE_CONSOLEURLS)
        for user_name, enc_password in user_passwords.items():
            item = {
                'account': account,
                'console_url': console_urls[account],
                'user_name': user_name,
                'encrypted_password': enc_password
            }
            credentials.append(item)

    columns = ['account', 'console_url', 'user_name', 'encrypted_password']
    print_output(ctx.obj['output'], credentials, columns)


@get.command()
@click.pass_context
def aws_route53_zones(ctx):
    zones = queries.get_dns_zones()

    results = []
    for zone in zones:
        zone_name = zone['name']
        zone_records = zone['records']
        zone_nameservers = dnsutils.get_nameservers(zone_name)
        item = {
            'domain': zone_name,
            'records': len(zone_records),
            'nameservers': zone_nameservers
        }
        results.append(item)

    columns = ['domain', 'records', 'nameservers']
    print_output(ctx.obj['output'], results, columns)


@get.command()
@click.argument('cluster_name')
@click.pass_context
def bot_login(ctx, cluster_name):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c['name'] == cluster_name]
    if len(clusters) == 0:
        print(f"{cluster_name} not found.")
        sys.exit(1)

    cluster = clusters[0]
    server = cluster['serverUrl']
    token = secret_reader.read(cluster['automationToken'])
    print(f"oc login --server {server} --token {token}")


@get.command()
@click.argument('name', default='')
@click.pass_context
def namespaces(ctx, name):
    namespaces = queries.get_namespaces()
    if name:
        namespaces = [ns for ns in namespaces if ns['name'] == name]

    columns = ['name', 'cluster.name', 'app.name']
    print_output(ctx.obj['output'], namespaces, columns)


@get.command()
@click.pass_context
def products(ctx):
    products = queries.get_products()
    columns = ['name', 'description']
    print_output(ctx.obj['output'], products, columns)


@describe.command()
@click.argument('name')
@click.pass_context
def product(ctx, name):
    products = queries.get_products()
    products = [p for p in products
                if p['name'].lower() == name.lower()]
    if len(products) != 1:
        print(f"{name} error")
        sys.exit(1)

    product = products[0]
    environments = product['environments']
    columns = ['name', 'description']
    print_output(ctx.obj['output'], environments, columns)


@get.command()
@click.pass_context
def environments(ctx):
    environments = queries.get_environments()
    columns = ['name', 'description', 'product.name']
    print_output(ctx.obj['output'], environments, columns)


@describe.command()
@click.argument('name')
@click.pass_context
def environment(ctx, name):
    environments = queries.get_environments()
    environments = [e for e in environments
                    if e['name'].lower() == name.lower()]
    if len(environments) != 1:
        print(f"{name} error")
        sys.exit(1)

    environment = environments[0]
    namespaces = environment['namespaces']
    columns = ['name', 'cluster.name', 'app.name']
    print_output(ctx.obj['output'], namespaces, columns)


@get.command()
@click.pass_context
def services(ctx):
    apps = queries.get_apps()
    columns = ['name', 'path', 'onboardingStatus']
    print_output(ctx.obj['output'], apps, columns)


@get.command()
@click.pass_context
def repos(ctx):
    repos = queries.get_repos()
    repos = [{'url': r} for r in repos]
    columns = ['url']
    print_output(ctx.obj['output'], repos, columns)


@get.command()
@click.argument('org_username')
@click.pass_context
def roles(ctx, org_username):
    users = queries.get_roles()
    users = [u for u in users if u['org_username'] == org_username]

    if len(users) == 0:
        print("User not found")
        return

    user = users[0]

    roles = []

    def add(d):
        for i, r in enumerate(roles):
            if all(d[k] == r[k] for k in ("type", "name", "resource")):
                roles.insert(i + 1, {
                    "type": "",
                    "name": "",
                    "resource": "",
                    "ref": d["ref"]
                })
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

            add({
                "type": "permission",
                "name": p["name"],
                "resource": r_name,
                "ref": role_name
            })

        for aws in role.get("aws_groups") or []:
            for policy in aws["policies"]:
                add({
                    "type": "aws",
                    "name": policy,
                    "resource": aws["account"]["name"],
                    "ref": aws["path"]
                })

        for a in role.get("access") or []:
            if a["cluster"]:
                cluster_name = a["cluster"]["name"]
                add({
                    "type": "cluster",
                    "name": a["clusterRole"],
                    "resource": cluster_name,
                    "ref": role_name
                })
            elif a["namespace"]:
                ns_name = a["namespace"]["name"]
                add({
                    "type": "namespace",
                    "name": a["role"],
                    "resource": ns_name,
                    "ref": role_name
                })

        for s in role.get("owned_saas_files") or []:
            add({
                "type": "saas_file",
                "name": "owner",
                "resource": s["name"],
                "ref": role_name
            })

    columns = ['type', 'name', 'resource', 'ref']
    print_output(ctx.obj['output'], roles, columns)


@get.command()
@click.argument('org_username', default='')
@click.pass_context
def users(ctx, org_username):
    users = queries.get_users()
    if org_username:
        users = [u for u in users if u['org_username'] == org_username]

    columns = ['org_username', 'github_username', 'name']
    print_output(ctx.obj['output'], users, columns)


@get.command()
@click.pass_context
def integrations(ctx):
    environments = queries.get_integrations()
    columns = ['name', 'description']
    print_output(ctx.obj['output'], environments, columns)


@get.command()
@click.pass_context
def quay_mirrors(ctx):
    apps = queries.get_quay_repos()

    mirrors = []
    for app in apps:
        quay_repos = app['quayRepos']

        if quay_repos is None:
            continue

        for qr in quay_repos:
            org_name = qr['org']['name']
            for item in qr['items']:
                mirror = item['mirror']

                if mirror is None:
                    continue

                name = item['name']
                url = item['mirror']['url']
                public = item['public']

                mirrors.append({
                    'repo': f'quay.io/{org_name}/{name}',
                    'public': public,
                    'upstream': url,
                })

    columns = ['repo', 'upstream', 'public']
    print_output(ctx.obj['output'], mirrors, columns)


@get.command()
@click.argument('aws_account')
@click.argument('identifier')
@click.pass_context
def service_owners_for_rds_instance(ctx, aws_account, identifier):
    namespaces = queries.get_namespaces()
    service_owners = []
    for namespace_info in namespaces:
        if namespace_info.get('terraformResources') is None:
            continue

        for tf in namespace_info.get('terraformResources'):
            if tf['provider'] == 'rds' and tf['account'] == aws_account and \
               tf['identifier'] == identifier:
                service_owners = namespace_info['app']['serviceOwners']
                break

    columns = ['name', 'email']
    print_output(ctx.obj['output'], service_owners, columns)


@get.command()
@click.pass_context
def sre_checkpoints(ctx):
    apps = queries.get_apps()

    parent_apps = {
        app['parentApp']['path']
        for app in apps
        if app.get('parentApp')
    }

    latest_sre_checkpoints = get_latest_sre_checkpoints()

    checkpoints_data = [
        {
            'name': full_name(app),
            'latest': latest_sre_checkpoints.get(full_name(app), '')
        }
        for app in apps
        if (app['path'] not in parent_apps and
            app['onboardingStatus'] == 'OnBoarded')
    ]

    checkpoints_data.sort(key=lambda c: c['latest'], reverse=True)

    columns = ['name', 'latest']
    print_output(ctx.obj['output'], checkpoints_data, columns)


def print_output(output, content, columns=[]):
    if output == 'table':
        print_table(content, columns)
    elif output == 'md':
        print_table(content, columns, table_format='github')
    elif output == 'json':
        print(json.dumps(content))
    elif output == 'yaml':
        print(yaml.dump(content))
    else:
        pass  # error


def print_table(content, columns, table_format='simple'):
    headers = [column.upper() for column in columns]
    table_data = []
    for item in content:
        row_data = []
        for column in columns:
            # example: for column 'cluster.name'
            # cell = item['cluster']['name']
            cell = item
            for token in column.split('.'):
                cell = cell.get(token) or {}
            if cell == {}:
                cell = ''
            if isinstance(cell, list):
                if table_format == 'github':
                    cell = '<br />'.join(cell)
                else:
                    cell = '\n'.join(cell)
            row_data.append(cell)
        table_data.append(row_data)

    print(tabulate(table_data, headers=headers, tablefmt=table_format))


@root.group()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def state(ctx):
    pass


@state.command()
@click.argument('integration', default='')
@click.pass_context
def ls(ctx, integration):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(integration, accounts, settings=settings)
    keys = state.ls()
    # if 'integration' is defined, the 0th token is empty
    table_content = [
        {'integration': k.split('/')[0] or integration,
         'key': '/'.join(k.split('/')[1:])}
        for k in keys]
    print_output('table', table_content, ['integration', 'key'])


@state.command()
@click.argument('integration')
@click.argument('key')
@click.pass_context
def get(ctx, integration, key):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(integration, accounts, settings=settings)
    value = state.get(key)
    print(value)


@state.command()
@click.argument('integration')
@click.argument('key')
@click.pass_context
def add(ctx, integration, key):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(integration, accounts, settings=settings)
    state.add(key)


@state.command()
@click.argument('integration')
@click.argument('key')
@click.argument('value')
@click.pass_context
def set(ctx, integration, key, value):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(integration, accounts, settings=settings)
    state.add(key, value=value, force=True)


@state.command()
@click.argument('integration')
@click.argument('key')
@click.pass_context
def rm(ctx, integration, key):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(integration, accounts, settings=settings)
    state.rm(key)


@root.command()
@click.argument('cluster')
@click.argument('namespace')
@click.argument('kind')
@click.argument('name')
@click.pass_context
def template(ctx, cluster, namespace, kind, name):
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(orb.NAMESPACES_QUERY)['namespaces']
    namespace_info = [n for n in namespaces
                      if n['cluster']['name'] == cluster
                      and n['name'] == namespace]
    if len(namespace_info) != 1:
        print(f"{cluster}/{namespace} error")
        sys.exit(1)

    [namespace_info] = namespace_info
    openshift_resources = namespace_info.get('openshiftResources')
    for r in openshift_resources:
        openshift_resource = orb.fetch_openshift_resource(r, namespace_info)
        if openshift_resource.kind.lower() != kind.lower():
            continue
        if openshift_resource.name != name:
            continue
        print_output('yaml', openshift_resource.body)
        break


@root.command()
@click.option('--app-name',
              default=None,
              help='app to act on.')
@click.option('--saas-file-name',
              default=None,
              help='saas-file to act on.')
@click.option('--env-name',
              default=None,
              help='environment to use for parameters.')
@click.pass_context
def saas_dev(ctx, app_name=None, saas_file_name=None, env_name=None):
    if env_name in [None, '']:
        print('env-name must be defined')
        return
    saas_files = queries.get_saas_files(saas_file_name, env_name, app_name,
                                        v1=True, v2=True)
    if not saas_files:
        print('no saas files found')
        sys.exit(1)
    for saas_file in saas_files:
        saas_file_parameters = \
            json.loads(saas_file.get('parameters') or '{}')
        for rt in saas_file['resourceTemplates']:
            url = rt['url']
            path = rt['path']
            rt_parameters = \
                json.loads(rt.get('parameters') or '{}')
            for target in rt['targets']:
                target_parameters = \
                    json.loads(target.get('parameters') or '{}')
                namespace = target['namespace']
                namespace_name = namespace['name']
                environment = namespace['environment']
                if environment['name'] != env_name:
                    continue
                ref = target['ref']
                environment_parameters = \
                    json.loads(environment.get('parameters') or '{}')
                parameters = {}
                parameters.update(environment_parameters)
                parameters.update(saas_file_parameters)
                parameters.update(rt_parameters)
                parameters.update(target_parameters)

                for replace_key, replace_value in parameters.items():
                    if not isinstance(replace_value, str):
                        continue
                    replace_pattern = '${' + replace_key + '}'
                    for k, v in parameters.items():
                        if not isinstance(v, str):
                            continue
                        if replace_pattern in v:
                            parameters[k] = \
                                v.replace(replace_pattern, replace_value)

                parameters_cmd = ''
                for k, v in parameters.items():
                    parameters_cmd += f" -p {k}=\"{v}\""
                raw_url = \
                    url.replace('github.com', 'raw.githubusercontent.com')
                if 'gitlab' in raw_url:
                    raw_url += '/raw'
                raw_url += '/' + ref
                raw_url += path
                cmd = "oc process --local --ignore-unknown-parameters" + \
                    f"{parameters_cmd} -f {raw_url}" + \
                    f" | oc apply -n {namespace_name} -f - --dry-run"
                print(cmd)


@root.command()
@click.argument('query')
@click.option('--output', '-o', help='output type', default='json',
              type=click.Choice(['json', 'yaml']))
def query(output, query):
    """Run a raw GraphQL query"""
    gqlapi = gql.get_api()
    print_output(output, gqlapi.query(query))


@root.command()
@click.argument('cluster')
@click.argument('query')
def promquery(cluster, query):
    """Run a PromQL query"""

    config_data = config.get_config()
    auth = {
        'path': config_data['promql-auth']['secret_path'],
        'field': 'token'
    }
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    prom_auth_creds = secret_reader.read(auth)
    prom_auth = requests.auth.HTTPBasicAuth(*prom_auth_creds.split(':'))

    url = f"https://prometheus.{cluster}.devshift.net/api/v1/query"

    response = requests.get(url, params={'query': query}, auth=prom_auth)
    response.raise_for_status()

    print(json.dumps(response.json(), indent=4))
