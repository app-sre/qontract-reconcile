import json
import click

import utils.gql as gql
import utils.config as config
import reconcile.queries as queries

from reconcile.cli import config_file


@click.group()
@config_file
@click.pass_context
def root(ctx, configfile):
    ctx.ensure_object(dict)
    config.init_from_toml(configfile)
    gql.init_from_config()


@root.group()
@click.pass_context
def get(ctx):
    pass


@get.command()
@click.pass_context
def settings(ctx):
    settings = queries.get_app_interface_settings()
    print(json.dumps(settings))


@get.command()
@click.pass_context
def aws_accounts(ctx):
    accounts = queries.get_aws_accounts()
    print(json.dumps(accounts))


@get.command()
@click.pass_context
def clusters(ctx):
    clusters = queries.get_clusters()
    print(json.dumps(clusters))


@get.command()
@click.pass_context
def namespaces(ctx):
    namespaces = queries.get_namespaces()
    print(json.dumps(namespaces))


@get.command()
@click.pass_context
def services(ctx):
    apps = queries.get_apps()
    print(json.dumps(apps))


@get.command()
@click.pass_context
def repos(ctx):
    repos = queries.get_repos()
    print(json.dumps(repos))


@get.command()
@click.pass_context
def users(ctx):
    users = queries.get_users()
    print(json.dumps(users))
