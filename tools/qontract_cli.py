import sys
import json
import yaml
import click

import utils.gql as gql
import utils.config as config
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
def namespaces(ctx, name):
    namespaces = queries.get_namespaces()
    if name:
        namespaces = [ns for ns in namespaces if ns['name'] == name]

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
                cell = cell[token]
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
def add(ctx, integration, key):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(integration, accounts, settings=settings)
    state.add(key)


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
