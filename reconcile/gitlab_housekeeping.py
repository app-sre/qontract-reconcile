import logging

from datetime import datetime, timedelta

from utils.config import get_config
from utils.gitlab_api import GitLabApi


def get_housekeeping_gitlab_api():
    config = get_config()

    gitlab_config = config['gitlab']
    server = gitlab_config['server']
    token = gitlab_config['token']
    project_id = gitlab_config['housekeeping']['project_id']

    return GitLabApi(server, token, project_id=project_id, ssl_verify=False)


def handle_stale_issues(dry_run, gl, days_interval):
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
                if not dry_run:
                    gl.close_issue(issue)
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
            # if the latest cancel note is under days_interval - remove 'stale' label
            current_interval = now.date() - latest_note_date.date()
            if current_interval <= timedelta(days=days_interval):
                logging.info(['remove_label', gl.project.name,
                              issue_iid, LABEL])
                if not dry_run:
                    gl.remove_label(issue, LABEL)


def run(dry_run=False, days_interval=15):
    gl = get_housekeeping_gitlab_api()
    handle_stale_issues(dry_run, gl, days_interval)
