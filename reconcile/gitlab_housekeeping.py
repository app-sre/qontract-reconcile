import logging
import gitlab

from datetime import datetime, timedelta

import reconcile.queries as queries

from utils.gitlab_api import GitLabApi


def handle_stale_items(dry_run, gl, days_interval, enable_closing, item_type):
    DATE_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'
    LABEL = 'stale'

    if item_type == 'issue':
        items = gl.get_issues(state='opened')
    elif item_type == 'merge-request':
        items = gl.get_merge_requests(state='opened')

    now = datetime.utcnow()
    for item in items:
        item_iid = item.attributes.get('iid')
        item_labels = item.attributes.get('labels')
        notes = item.notes.list()
        note_dates = \
            [datetime.strptime(note.attributes.get('updated_at'), DATE_FORMAT)
             for note in notes]
        update_date = max(d for d in note_dates) if note_dates else now

        # if item is over days_interval
        current_interval = now.date() - update_date.date()
        if current_interval > timedelta(days=days_interval):
            # if item does not have 'stale' label - add it
            if LABEL not in item_labels:
                logging.info(['add_label', gl.project.name, item_type,
                              item_iid, LABEL])
                if not dry_run:
                    gl.add_label(item, item_type, LABEL)
            # if item has 'stale' label - close it
            else:
                logging.info(['close_item', gl.project.name,
                              item_type, item_iid])
                if enable_closing:
                    if not dry_run:
                        gl.close(item)
                else:
                    warning_message = \
                        '\'close_item\' action is not enabled. ' + \
                        'Please run the integration manually ' + \
                        'with the \'--enable-deletion\' flag.'
                    logging.warning(warning_message)
        # if item is under days_interval
        else:
            if LABEL not in item_labels:
                continue

            # if item has 'stale' label - check the notes
            cancel_notes = [n for n in notes
                            if n.attributes.get('body') ==
                            '/{} cancel'.format(LABEL)]
            if not cancel_notes:
                continue

            cancel_notes_dates = \
                [datetime.strptime(
                    note.attributes.get('updated_at'), DATE_FORMAT)
                 for note in cancel_notes]
            latest_cancel_note_date = max(d for d in cancel_notes_dates)
            # if the latest cancel note is under
            # days_interval - remove 'stale' label
            current_interval = now.date() - latest_cancel_note_date.date()
            if current_interval <= timedelta(days=days_interval):
                logging.info(['remove_label', gl.project.name,
                              item_type, item_iid, LABEL])
                if not dry_run:
                    gl.remove_label(item, item_type, LABEL)


def rebase_merge_requests(dry_run, gl, rebase_limit):
    HOLD_LABELS = [
        'blocked/devtools-bot-access',
        'do-not-merge/hold',
        'awaiting-approval',
        'stale'
    ]
    mrs = gl.get_merge_requests(state='opened')
    rebases = 0
    for mr in reversed(mrs):
        if mr.merge_status == 'cannot_be_merged':
            continue
        if mr.work_in_progress:
            continue
        labels = mr.attributes.get('labels')
        hold_rebase = any(l in HOLD_LABELS for l in labels)
        if hold_rebase:
            continue

        target_branch = mr.target_branch
        head = gl.project.commits.list(ref_name=target_branch)[0].id
        result = gl.project.repository_compare(mr.sha, head)
        if len(result['commits']) == 0:  # rebased
            continue

        logging.info(['rebase', gl.project.name, mr.iid])
        if not dry_run and rebases < rebase_limit:
            try:
                mr.rebase()
                rebases += 1
            except gitlab.exceptions.GitlabMRRebaseError as e:
                logging.error('unable to rebase {}: {}'.format(mr.iid, e))


def merge_merge_requests(dry_run, gl, merge_limit):
    MERGE_LABELS = ['lgtm', 'automerge']

    mrs = gl.get_merge_requests(state='opened')
    merges = 0
    for mr in reversed(mrs):
        if mr.merge_status == 'cannot_be_merged':
            continue
        if mr.work_in_progress:
            continue

        target_branch = mr.target_branch
        head = gl.project.commits.list(ref_name=target_branch)[0].id
        result = gl.project.repository_compare(mr.sha, head)
        if len(result['commits']) != 0:  # not rebased
            continue

        labels = mr.attributes.get('labels')
        if not labels:
            continue

        good_to_merge = all(l in MERGE_LABELS for l in labels)
        if not good_to_merge:
            continue

        pipelines = mr.pipelines()
        if not pipelines:
            continue

        # posibble statuses:
        # running, pending, success, failed, canceled, skipped
        incomplete_pipelines = \
            [p for p in pipelines
             if p['status'] in ['running', 'pending']]
        if incomplete_pipelines:
            continue

        last_pipeline_result = pipelines[0]['status']
        if last_pipeline_result != 'success':
            continue

        logging.info(['merge', gl.project.name, mr.iid])
        if not dry_run and merges < merge_limit:
            mr.merge()
            merges += 1


def run(gitlab_project_id, dry_run=False, days_interval=15,
        enable_closing=False, limit=1):
    instance = queries.get_gitlab_instance()
    gl = GitLabApi(instance, project_id=gitlab_project_id)
    handle_stale_items(dry_run, gl, days_interval, enable_closing,
                       'issue')
    handle_stale_items(dry_run, gl, days_interval, enable_closing,
                       'merge-request')
    rebase_merge_requests(dry_run, gl, limit)
    merge_merge_requests(dry_run, gl, limit)
