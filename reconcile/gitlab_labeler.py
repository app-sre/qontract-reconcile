import os
import logging

import reconcile.queries as queries

from reconcile.gitlab_housekeeping import MERGE_LABELS_PRIORITY, HOLD_LABELS
from reconcile.utils.gitlab_api import GitLabApi


QONTRACT_INTEGRATION = 'gitlab-labeler'


def guess_labels(project_labels, changed_paths):
    """
    Guess labels returns a list of labels from the project labels
    that contain parts of the changed paths.
    This is the first form of guessing, which will likely be adjusted.
    """
    not_allowed_labels = MERGE_LABELS_PRIORITY + HOLD_LABELS
    ignore_tokens = ['cicd', 'saas', 'rds', 'services']
    guesses = set()
    for label in project_labels:
        if label in not_allowed_labels:
            continue
        for path in changed_paths:
            path_dir = os.path.dirname(path)
            path_tokens = path_dir.split('/')
            matches = [t for t in path_tokens if t
                       and t in label
                       and t not in ignore_tokens]
            if matches:
                guesses.add(label)

    return list(guesses)


def run(dry_run, gitlab_project_id=None, gitlab_merge_request_id=None):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, project_id=gitlab_project_id,
                   settings=settings)
    project_labels = gl.get_project_labels()
    labels = gl.get_merge_request_labels(gitlab_merge_request_id)
    changed_paths = \
        gl.get_merge_request_changed_paths(gitlab_merge_request_id)
    guessed_labels = guess_labels(project_labels, changed_paths)
    labels_to_add = [l for l in guessed_labels if l not in labels]
    if labels_to_add:
        logging.info(['add_labels', labels_to_add])
        gl.add_labels_to_merge_request(gitlab_merge_request_id, labels_to_add)
