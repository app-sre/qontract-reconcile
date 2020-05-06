import sys
import json
import yaml
import click

import utils.gql as gql
import utils.config as config
import utils.secret_reader as secret_reader
import reconcile.queries as queries
import reconcile.openshift_resources as ocr

from tabulate import tabulate

from utils.state import State
from utils.environ import environ
from reconcile.cli import config_file


def output(function):
    function = click.option('--output', '-o',
                            help='output type',
                            default='table',
                            type=click.Choice([
                                'table',
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
    columns = ['vault', 'kubeBinary', 'pullRequestGateway']
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

    columns = ['name', 'consoleUrl', 'kibanaUrl']
    print_output(ctx.obj['output'], clusters, columns)


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
@click.argument('cluster_name')
@click.pass_context
def bot_login(ctx, cluster_name):
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c['name'] == cluster_name]
    if len(clusters) == 0:
        print(f"{cluster_name} not found.")
        sys.exit(1)

    cluster = clusters[0]
    settings = queries.get_app_interface_settings()
    server = cluster['serverUrl']
    token = secret_reader.read(cluster['automationToken'], settings=settings)
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
def acme_accounts(ctx):
    namespaces = queries.get_namespaces()
    acme_usage = {}
    for namespace_info in namespaces:
        if namespace_info.get('openshiftAcme') is None:
            continue
        namespace_name = namespace_info['name']
        cluster_name = namespace_info['cluster']['name']
        acme_secret = \
            namespace_info['openshiftAcme']['accountSecret']['path']
        acme_usage.setdefault(acme_secret, [])
        acme_usage[acme_secret].append(f"{cluster_name}/{namespace_name}")

    usage = [{'path': k, 'usage': len(v), 'namespaces': ', '.join(v)}
             for k, v in acme_usage.items()]

    columns = ['path', 'usage', 'namespaces']
    print_output(ctx.obj['output'], usage, columns)


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
    columns = ['name']
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


def print_output(output, content, columns=[]):
    if output == 'table':
        print_table(content, columns)
    elif output == 'json':
        print(json.dumps(content))
    elif output == 'yaml':
        print(yaml.dump(content))
    else:
        pass  # error


def print_table(content, columns):
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
            row_data.append(cell)
        table_data.append(row_data)

    print(tabulate(table_data, headers=headers))


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
    namespaces = gqlapi.query(ocr.NAMESPACES_QUERY)['namespaces']
    namespace_info = [n for n in namespaces
                      if n['cluster']['name'] == cluster
                      and n['name'] == namespace]
    if len(namespace_info) != 1:
        print(f"{cluster}/{namespace} error")
        sys.exit(1)

    [namespace_info] = namespace_info
    openshift_resources = namespace_info.get('openshiftResources')
    for r in openshift_resources:
        openshift_resource = ocr.fetch_openshift_resource(r, namespace_info)
        if openshift_resource.kind.lower() != kind.lower():
            continue
        if openshift_resource.name != name:
            continue
        print_output('yaml', openshift_resource.body)
        break


@root.command()
@click.argument('query')
@click.option('--output', '-o', help='output type', default='json',
              type=click.Choice(['json', 'yaml']))
def query(output, query):
    """Run a raw GraphQL query"""
    gqlapi = gql.get_api()
    print_output(output, gqlapi.query(query))
