import json
import yaml
import click

import utils.gql as gql
import utils.config as config
import reconcile.queries as queries

from tabulate import tabulate

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
@click.pass_context
def aws_accounts(ctx):
    accounts = queries.get_aws_accounts()
    columns = ['name', 'consoleUrl']
    print_output(ctx.obj['output'], accounts, columns)


@get.command()
@click.pass_context
def clusters(ctx):
    clusters = queries.get_clusters()
    columns = ['name', 'consoleUrl', 'kibanaUrl']
    print_output(ctx.obj['output'], clusters, columns)


@get.command()
@click.pass_context
def namespaces(ctx):
    namespaces = queries.get_namespaces()
    columns = ['name', 'cluster.name', 'app.name']
    print_output(ctx.obj['output'], namespaces, columns)


@get.command()
@click.pass_context
def services(ctx):
    apps = queries.get_apps()
    columns = []
    print_output(ctx.obj['output'], apps, columns)


@get.command()
@click.pass_context
def repos(ctx):
    repos = queries.get_repos()
    columns = []
    print_output(ctx.obj['output'], repos, columns)


@get.command()
@click.pass_context
def users(ctx):
    users = queries.get_users()
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
