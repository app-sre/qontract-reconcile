import yaml
import click
import logging

from datetime import datetime, timezone
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
                self.get_production_promotions(self.app.get('promotions')),
                self.get_merge_activity(self.app.get('merge_activity'))
            )
        }

    def to_yaml(self):
        return yaml.safe_dump(self.content())

    def to_message(self):
        return {
            'file_path': self.path,
            'content': self.to_yaml()
        }

    def get_production_promotions(self, promotions):
        header = 'Number of Production promotions:'
        return self.get_activity_content(header, promotions)

    def get_merge_activity(self, merge_activity):
        header = 'Number of merges to master:'
        return self.get_activity_content(header, merge_activity)

    @staticmethod
    def get_activity_content(header, activity):
        if not activity:
            return ''

        lines = [f"{repo}: {results[0]} ({int(results[1])}% success)"
                 for repo, results in activity.items()]
        content = header + '\n' + '\n'.join(lines) if lines else ''

        return content


def get_apps_data(date, month_delta=1):
    apps = queries.get_apps()
    jjb = init_jjb()
    saas_jobs = jjb.get_all_jobs(job_type='saas-deploy')
    build_master_jobs = jjb.get_all_jobs(job_type='build-master')
    jenkins_map = jenkins_base.get_jenkins_map()
    time_limit = date - relativedelta(months=month_delta)
    timestamp_limit = \
        int(time_limit.replace(tzinfo=timezone.utc).timestamp())
    saas_build_history = \
        get_build_history(jenkins_map, saas_jobs, timestamp_limit)
    build_master_build_history = \
        get_build_history(jenkins_map, build_master_jobs, timestamp_limit)

    for app in apps:
        if not app['codeComponents']:
            continue

        app_name = app['name']
        logging.info(f"collecting promotions for {app_name}")
        app['promotions'] = {}
        saas_repos = [c['url'] for c in app['codeComponents']
                      if c['resource'] == 'saasrepo']
        for sr in saas_repos:
            sr_history = saas_build_history.get(sr)
            if not sr_history:
                continue
            successes = [h for h in sr_history if h == 'SUCCESS']
            app['promotions'][sr] = \
                (len(sr_history), (len(successes) / len(sr_history) * 100))

        logging.info(f"collecting merge activity for {app_name}")
        app['merge_activity'] = {}
        code_repos = [c['url'] for c in app['codeComponents']
                      if c['resource'] == 'upstream']
        for cr in code_repos:
            cr_history = build_master_build_history.get(cr)
            if not cr_history:
                continue
            successes = [h for h in cr_history if h == 'SUCCESS']
            app['merge_activity'][cr] = \
                (len(cr_history), (len(successes) / len(cr_history) * 100))

    return apps


def get_build_history(jenkins_map, jobs, timestamp_limit):
    history = {}
    for instance, jobs in jobs.items():
        jenkins = jenkins_map[instance]
        for job in jobs:
            logging.info(f"getting build history for {job['name']}")
            build_history = \
                jenkins.get_build_history(job['name'], timestamp_limit)
            repo_url = get_repo_url(job)
            history[repo_url] = build_history

    return history


def get_repo_url(job):
    repo_url_raw = job['properties'][0]['github']['url']
    return repo_url_raw.strip('/').replace('.git', '')


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
    apps = get_apps_data(now)

    reports = [Report(app, now).to_message() for app in apps]

    for report in reports:
        logging.info(['create_report', report['file_path']])
        print(report)

    if not dry_run:
        gw = prg.init(gitlab_project_id=gitlab_project_id,
                      override_pr_gateway_type='gitlab')
        mr = gw.create_app_interface_reporter_mr(reports)
        logging.info(['created_mr', mr.web_url])
