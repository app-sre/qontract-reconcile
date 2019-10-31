import logging
from datetime import datetime

import click
import yaml

import reconcile.pull_request_gateway as prg
import utils.config as config
import utils.gql as gql
from reconcile.cli import (
    config_file,
    log_level,
    dry_run,
    init_log_level,
    gitlab_project_id
)

APPS_QUERY = """
{
  apps: apps_v1 {
    path
    name
  }
}
"""


class Report(object):
    def __init__(self, app, date):
        # standard date format
        if hasattr(date, 'strftime'):
            date = date.strftime('%Y-%m-%d')

        self.app = app
        self.date = date

    @property
    def path(self):
        return 'data/reports/{}/{}.yml'.format(
            self.app['name'],
            self.date
        )

    def content(self):
        return {
            '$schema': '/app-sre/report-1.yml',
            'labels': {'app': self.app['name']},
            'name': self.app['name'],
            'app': {'$ref': self.app['path']},
            'date': self.date,
            'content': 'report for {} on {}'.format(
                self.app['name'],
                self.date
            )
        }

    def to_yaml(self):
        return yaml.safe_dump(self.content())

    def to_message(self):
        return {
            'file_path': self.path,
            'content': self.to_yaml()
        }


@click.command()
@config_file
@dry_run
@log_level
# TODO: @environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
def main(configfile, dry_run, log_level, gitlab_project_id):
    config.init_from_toml(configfile)
    init_log_level(log_level)
    config.init_from_toml(configfile)
    gql.init_from_config()
    gqlapi = gql.get_api()

    now = datetime.now()

    apps = gqlapi.query(APPS_QUERY)['apps']

    reports = [Report(app, now).to_message() for app in apps]

    for report in reports:
        logging.info(['create_report', report['file_path']])

    if not dry_run:
        gw = prg.init(gitlab_project_id=gitlab_project_id,
                      override_pr_gateway_type='gitlab')
        mr = gw.create_app_interface_reporter_mr(reports)
        logging.info(['create_mr', mr.web_url])
