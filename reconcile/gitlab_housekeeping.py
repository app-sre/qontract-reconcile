import logging

from datetime import datetime, timedelta

import utils.gql as gql

from utils.gitlab_api import GitLabApi
from reconcile.queries import GITLAB_INSTANCES_QUERY


def handle_stale_issues(dry_run, gl, days_interval, enable_close_issues):
    DATE_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'
    LABEL = 'stale'

    issues = gl.get_issues(state='opened')
    now = datetime.utcnow()
    for issue in issues:
        issue_iid = issue.attributes.get('iid')
        issue_labels = issue.attributes.get('labels')
        updated_at = issue.attributes.get('updated_at')
        update_date = datetime.strptime(updated_at, DATE_FORMAT)

        # if issue is over days_interval
        current_interval = now.date() - update_date.date()
        if current_interval > timedelta(days=days_interval):
            # if issue does not have 'stale' label - add it
            if LABEL not in issue_labels:
                logging.info(['add_label', gl.project.name, issue_iid, LABEL])
                if not dry_run:
                    gl.add_label(issue, LABEL)
            # if issue has 'stale' label - close it
            else:
                logging.info(['close_issue', gl.project.name, issue_iid])
                if enable_close_issues:
                    if not dry_run:
                        gl.close_issue(issue)
                else:
                    warning_message = \
                        '\'close_issue\' action is not enabled. ' + \
                        'Please run the integration manually ' + \
                        'with the \'--enable-close-issues\' flag.'
                    logging.warning(warning_message)
        # if issue is under days_interval
        else:
            if LABEL not in issue_labels:
                continue

            # if issue has 'stale' label - check the notes
            notes = issue.notes.list()
            cancel_notes = [n for n in notes
                            if n.attributes.get('body') ==
                            '/{} cancel'.format(LABEL)]
            if not cancel_notes:
                continue

            notes_dates = \
                [datetime.strptime(
                    note.attributes.get('updated_at'), DATE_FORMAT)
                 for note in cancel_notes]
            latest_note_date = max(d for d in notes_dates)
            # if the latest cancel note is under
            # days_interval - remove 'stale' label
            current_interval = now.date() - latest_note_date.date()
            if current_interval <= timedelta(days=days_interval):
                logging.info(['remove_label', gl.project.name,
                              issue_iid, LABEL])
                if not dry_run:
                    gl.remove_label(issue, LABEL)


def run(project_id, dry_run=False, days_interval=15,
        enable_close_issues=False):
    gqlapi = gql.get_api()
    # assuming a single GitLab instance for now
    instance = gqlapi.query(GITLAB_INSTANCES_QUERY)['instances'][0]
    gl = GitLabApi(instance, project_id=project_id, ssl_verify=False)
    handle_stale_issues(dry_run, gl, days_interval, enable_close_issues)
