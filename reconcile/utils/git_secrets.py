import logging
import os
import shutil
import tempfile
from subprocess import (
    PIPE,
    Popen,
)

import requests
from sretoolbox.utils import retry

from reconcile.utils import git
from reconcile.utils.defer import defer


@defer
@retry()
def scan_history(repo_url, existing_keys, defer=None):
    # pylint: disable=consider-using-with
    logging.info("scanning {}".format(repo_url))
    if requests.get(repo_url, timeout=60).status_code == 404:
        logging.info("not found {}".format(repo_url))
        return []

    wd = tempfile.mkdtemp()
    defer(lambda: cleanup(wd))

    git.clone(repo_url, wd)
    DEVNULL = open(os.devnull, "w")
    proc = Popen(["git", "secrets", "--register-aws"], cwd=wd, stdout=DEVNULL)
    proc.communicate()
    proc = Popen(["git", "secrets", "--scan-history"], cwd=wd, stdout=PIPE, stderr=PIPE)
    _, err = proc.communicate()
    if proc.returncode == 0:
        return []

    logging.info("found suspects in {}".format(repo_url))
    suspected_files = get_suspected_files(err.decode("utf-8"))
    leaked_keys = get_leaked_keys(wd, suspected_files, existing_keys)
    if leaked_keys:
        logging.info("found suspected leaked keys: {}".format(leaked_keys))

    return leaked_keys


def cleanup(wd):
    try:
        shutil.rmtree(wd)
    except Exception:
        pass


def get_suspected_files(error):
    suspects = []
    for e in error.split("\n"):
        if e == "":
            break
        if e.startswith("warning"):
            continue
        commit_path_split = e.split(" ")[0].split(":")
        commit, path = commit_path_split[0], commit_path_split[1]

        suspects.append((commit, path))
    return set(suspects)


def get_leaked_keys(repo_wd, suspected_files, existing_keys):
    all_leaked_keys = []
    for s in suspected_files:
        commit, file_relative_path = s[0], s[1]
        git.checkout(commit, repo_wd)
        file_path = os.path.join(repo_wd, file_relative_path)
        with open(file_path, "r") as f:
            content = f.read()
        leaked_keys = [key for key in existing_keys if key in content]
        all_leaked_keys.extend(leaked_keys)

    return all_leaked_keys
