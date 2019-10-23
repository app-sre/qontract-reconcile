import os
import tempfile
import shutil
import logging

from utils.defer import defer

from git import Repo
from os import path
from subprocess import PIPE, Popen, STDOUT


@defer
def scan_history(repo_url, existing_keys, defer=None):
    logging.info('scanning {}'.format(repo_url))
    wd = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(wd))

    repo = Repo.clone_from(repo_url, wd)
    DEVNULL = open(os.devnull, 'w')
    proc = Popen(['git', 'secrets', '--register-aws'],
                 cwd=wd, stdout=DEVNULL)
    proc.communicate()
    proc = Popen(['git', 'secrets', '--scan-history'],
                 cwd=wd, stdout=PIPE, stderr=PIPE)
    _, err = proc.communicate()
    if proc.returncode == 0:
        return []

    logging.info('found suspects in {}'.format(repo_url))
    suspcted_files = get_suspected_files(err)
    leaked_keys = get_leaked_keys(repo, suspcted_files, existing_keys)
    if leaked_keys:
        logging.info('found suspected leaked keys: {}'.format(leaked_keys))

    return leaked_keys


def get_suspected_files(error):
    suspects = []
    for e in error.split('\n'):
        if e == "":
            break
        if e.startswith('warning'):
            continue
        commit_path_split = e.split(' ')[0].split(':')
        commit, path = commit_path_split[0], commit_path_split[1]

        suspects.append((commit, path))
    return set(suspects)


def get_leaked_keys(repo, suspcted_files, existing_keys):
    all_leaked_keys = []
    for s in suspcted_files:
        commit, file_relative_path = s[0], s[1]
        repo.head.reference = repo.commit(commit)
        repo.head.reset(index=True, working_tree=True)
        file_path = path.join(repo.working_dir, file_relative_path)
        with open(file_path, 'r') as f:
            content = f.read()
        leaked_keys = [key for key in existing_keys if key in content]
        all_leaked_keys.extend(leaked_keys)

    return all_leaked_keys
