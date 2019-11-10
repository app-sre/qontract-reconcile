import yaml
import click
import logging

from datetime import datetime
from dateutil.relativedelta import relativedelta

import utils.gql as gql
import utils.config as config
import reconcile.queries as queries
import reconcile.pull_request_gateway as prg
import reconcile.jenkins_plugins as jenkins_base

from reconcile.jenkins_job_builder import init_jjb
from reconcile.cli import (
    config_file,
    log_level,
    dry_run,
    init_log_level,
    gitlab_project_id
)


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
        report_content = """report for {} on {}:
{}
"""
        return {
            '$schema': '/app-sre/report-1.yml',
            'labels': {'app': self.app['name']},
            'name': self.app['name'],
            'app': {'$ref': self.app['path']},
            'date': self.date,
            'content': report_content.format(
                self.app['name'],
                self.date,
                self.get_production_promotions()
            )
        }

    def to_yaml(self):
        return yaml.safe_dump(self.content())

    def to_message(self):
        return {
            'file_path': self.path,
            'content': self.to_yaml()
        }

    def get_production_promotions(self):
        content = """Number of Production promotions:
{}"""
        return content


def get_apps_data():
    apps = queries.get_apps()
    jjb = init_jjb()
    jenkins_map = jenkins_base.get_jenkins_map()
    jobs_history = jjb.get_jobs_history(jenkins_map, job_type='saas-deploy')
    import sys
    sys.exit()

    webhooks = jjb.get_job_webhooks_data(include_github=True)
    for app in apps:
        print(app['name'])
        app['promotions'] = []
        if not app['codeComponents']:
            continue
        saas_repos = [c['url'] for c in app['codeComponents']
                      if c['resource'] == 'saasrepo']
        for sr in saas_repos:
            print(sr)
            print(webhooks)
            job_urls = [w['job_url'] for w in webhooks[sr]
                        if w['trigger'] == 'push']
            for job_url in job_urls:
                print(job_url)

    return apps


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

    now = datetime.now()

    apps = get_apps_data()

    reports = [Report(app, now).to_message() for app in apps]

    for report in reports:
        logging.info(['create_report', report['file_path']])
        print(report)

    if not dry_run:
        gw = prg.init(gitlab_project_id=gitlab_project_id,
                      override_pr_gateway_type='gitlab')
        mr = gw.create_app_interface_reporter_mr(reports)
        logging.info(['created_mr', mr.web_url])
