import logging

from datetime import datetime, timedelta

import gitlab

from sretoolbox.utils import retry

import reconcile.queries as queries

from reconcile.utils.gitlab_api import GitLabApi

LGTM_LABEL = 'lgtm'
MERGE_LABELS_PRIORITY = ['bot/approved', LGTM_LABEL, 'bot/automerge']
SAAS_FILE_LABEL = 'saas-file-update'
REBASE_LABELS_PRIORITY = MERGE_LABELS_PRIORITY + [SAAS_FILE_LABEL]
HOLD_LABELS = ['awaiting-approval', 'blocked/bot-access', 'hold', 'bot/hold',
               'do-not-merge/hold', 'do-not-merge/pending-review']

QONTRACT_INTEGRATION = 'gitlab-housekeeping'


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


def is_good_to_merge(merge_label, labels):
    return merge_label in labels and \
        not any(l in HOLD_LABELS for l in labels)


def rebase_merge_requests(dry_run, gl, rebase_limit, wait_for_pipeline=False):
    mrs = gl.get_merge_requests(state='opened')
    rebases = 0
    for rebase_label in REBASE_LABELS_PRIORITY:
        for mr in reversed(mrs):
            if mr.merge_status == 'cannot_be_merged':
                continue
            if mr.work_in_progress:
                continue
            if len(mr.commits()) == 0:
                continue

            labels = mr.attributes.get('labels')
            if not labels:
                continue

            good_to_rebase = is_good_to_merge(rebase_label, labels)
            if not good_to_rebase:
                continue

            target_branch = mr.target_branch
            head = gl.project.commits.list(ref_name=target_branch)[0].id
            result = gl.project.repository_compare(mr.sha, head)
            if len(result['commits']) == 0:  # rebased
                continue

            if wait_for_pipeline:
                pipelines = mr.pipelines()
                if not pipelines:
                    continue

                # possible statuses:
                # running, pending, success, failed, canceled, skipped
                incomplete_pipelines = \
                    [p for p in pipelines
                     if p['status'] in ['running']]
                if incomplete_pipelines:
                    continue

            logging.info(['rebase', gl.project.name, mr.iid])
            if not dry_run and rebases < rebase_limit:
                try:
                    mr.rebase()
                    rebases += 1
                except gitlab.exceptions.GitlabMRRebaseError as e:
                    logging.error('unable to rebase {}: {}'.format(mr.iid, e))


@retry(max_attempts=10)
def merge_merge_requests(dry_run, gl, merge_limit, rebase, insist=False,
                         wait_for_pipeline=False):
    mrs = gl.get_merge_requests(state='opened')
    merges = 0
    for merge_label in MERGE_LABELS_PRIORITY:
        for mr in reversed(mrs):
            if mr.merge_status == 'cannot_be_merged':
                continue
            if mr.work_in_progress:
                continue
            if len(mr.commits()) == 0:
                continue

            labels = mr.attributes.get('labels')
            if not labels:
                continue

            good_to_merge = is_good_to_merge(merge_label, labels)
            if not good_to_merge:
                continue

            if SAAS_FILE_LABEL in labels and LGTM_LABEL in labels:
                logging.warning(
                    f"[{gl.project.name}/{mr.iid}] 'lgtm' label not " +
                    f"suitable for saas file update. removing 'lgtm' label"
                )
                gl.remove_label_from_merge_request(mr.iid, LGTM_LABEL)
                continue

            target_branch = mr.target_branch
            head = gl.project.commits.list(ref_name=target_branch)[0].id
            result = gl.project.repository_compare(mr.sha, head)
            if rebase and len(result['commits']) != 0:  # not rebased
                continue

            pipelines = mr.pipelines()
            if not pipelines:
                continue

            if wait_for_pipeline:
                # possible statuses:
                # running, pending, success, failed, canceled, skipped
                incomplete_pipelines = \
                    [p for p in pipelines
                     if p['status'] in ['running']]
                if incomplete_pipelines:
                    if insist:
                        raise Exception(f'insisting on {merge_label}')
                    else:
                        continue

            last_pipeline_result = pipelines[0]['status']
            if last_pipeline_result != 'success':
                continue

            logging.info(['merge', gl.project.name, mr.iid])
            if not dry_run and merges < merge_limit:
                try:
                    mr.merge()
                    if rebase:
                        return
                    merges += 1
                except gitlab.exceptions.GitlabMRClosedError as e:
                    logging.error('unable to merge {}: {}'.format(mr.iid, e))


def run(dry_run, wait_for_pipeline):
    default_days_interval = 15
    default_limit = 8
    default_enable_closing = False
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    repos = queries.get_repos_gitlab_housekeeping(server=instance['url'])

    for repo in repos:
        hk = repo['housekeeping']
        project_url = repo['url']
        days_interval = hk.get('days_interval') or default_days_interval
        enable_closing = hk.get('enable_closing') or default_enable_closing
        limit = hk.get('limit') or default_limit
        gl = GitLabApi(instance, project_url=project_url, settings=settings)
        handle_stale_items(dry_run, gl, days_interval, enable_closing,
                           'issue')
        handle_stale_items(dry_run, gl, days_interval, enable_closing,
                           'merge-request')
        rebase = hk.get('rebase')
        try:
            merge_merge_requests(dry_run, gl, limit, rebase, insist=True,
                                 wait_for_pipeline=wait_for_pipeline)
        except Exception:
            merge_merge_requests(dry_run, gl, limit, rebase,
                                 wait_for_pipeline=wait_for_pipeline)
        if rebase:
            rebase_merge_requests(dry_run, gl, limit,
                                  wait_for_pipeline=wait_for_pipeline)
