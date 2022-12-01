import logging
import os
from collections.abc import Iterable
from typing import Optional

from reconcile import queries
from reconcile.gitlab_housekeeping import (
    HOLD_LABELS,
    MERGE_LABELS_PRIORITY,
)
from reconcile.utils.gitlab_api import GitLabApi

LABEL_COLOR = "#0000FF"  # Color blue in hex for labels
QONTRACT_INTEGRATION = "gitlab-labeler"


def get_app_list() -> dict:
    """
    Get a list of all services managed by app-interface with the parent app
    and the onboarding status of the service.
    """
    apps = queries.get_apps()
    app_info = {
        a["name"]: {
            "onboardingStatus": a["onboardingStatus"],
            "parentApp": a["parentApp"],
        }
        for a in apps
    }
    return app_info


def get_parents_list() -> set[str]:
    """
    Get a set of all service names that are parents of another service
    """
    parent_set = set()
    apps = queries.get_apps()
    for a in apps:
        if a["parentApp"] is not None:
            parent_set.add(a["parentApp"]["name"])

    return parent_set


def guess_onboarding_status(
    changed_paths: Iterable[str], apps: dict[str, dict], parent_apps: set[str]
) -> Optional[str]:
    """
    Guess the service name of a given MR from the changed paths of the
    MR. This will allow to add the onboarding status to the MR's as label
    In case that multiple apps are found, will return None
    """
    labels = set()
    for path in changed_paths:
        if "data/services/" in path:
            path_slices = path.split("/")
            app_name = path_slices[2]

            if app_name in parent_apps:
                child_app = path_slices[3]
                if child_app in apps:
                    app = apps[child_app]
                    labels.add(app["onboardingStatus"])
                else:
                    app = apps[app_name]
                    labels.add(app["onboardingStatus"])
            else:
                if app_name in apps:
                    app = apps[app_name]
                    labels.add(app["onboardingStatus"])
                else:
                    logging.debug("Error getting app name " + path)

    if len(labels) == 1:
        return labels.pop()
    else:
        return None


def guess_labels(
    project_labels: Iterable[str], changed_paths: Iterable[str]
) -> Iterable[str]:
    """
    Guess labels returns a list of labels from the project labels
    that contain parts of the changed paths.
    This is the first form of guessing, which will likely be adjusted.
    """
    not_allowed_labels = MERGE_LABELS_PRIORITY + HOLD_LABELS
    ignore_tokens = ["cicd", "saas", "rds", "services"]

    apps = get_app_list()
    parent_apps = get_parents_list()

    guesses = set()
    tenants = []
    matches = []

    for path in changed_paths:
        path_dir = os.path.dirname(path)
        path_tokens = path_dir.split("/")

        if "data/services/" in path:
            tenants += [t for t in path_tokens if t not in ignore_tokens and t in apps]

        matches += [
            t for t in path_tokens if t not in ignore_tokens and t in project_labels
        ]

    for t in tenants:
        if t not in not_allowed_labels:
            guesses.add("tenant-" + t)

    for m in matches:
        if m not in not_allowed_labels:
            guesses.add(m)

    onboarding_status = guess_onboarding_status(changed_paths, apps, parent_apps)
    if onboarding_status:
        guesses.add(onboarding_status)

    return guesses


def run(dry_run, gitlab_project_id=None, gitlab_merge_request_id=None) -> None:
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, project_id=gitlab_project_id, settings=settings)
    project_labels = gl.get_project_labels()
    labels = gl.get_merge_request_labels(gitlab_merge_request_id)
    changed_paths = gl.get_merge_request_changed_paths(gitlab_merge_request_id)
    guessed_labels = guess_labels(project_labels, changed_paths)
    labels_to_add = [b for b in guessed_labels if b not in labels]
    labels_to_create = [b for b in labels_to_add if b not in project_labels]

    # This integration cannot check dry-run mode as it's always running with
    # dry_run flag to true.
    if labels_to_create:
        logging.info(["create_labels", labels_to_create])
        for label in labels_to_create:
            gl.create_label(label, LABEL_COLOR)

    if labels_to_add:
        logging.info(["add_labels", labels_to_add])
        gl.add_labels_to_merge_request(gitlab_merge_request_id, labels_to_add)
