import os
import tempfile
import shutil
import logging

from git import Repo
from subprocess import PIPE, Popen, STDOUT

from utils.defer import defer

@defer
def scan_history(repo_url, defer=None):
    logging.info('scanning {}'.format(repo_url))
    wd = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(wd))

    Repo.clone_from(repo_url, wd)
    DEVNULL = open(os.devnull, 'w')
    proc = Popen(['git', 'secrets', '--register-aws'],
                 cwd=wd, stdout=DEVNULL)
    proc.communicate()
    proc = Popen(['git', 'secrets', '--scan-history'],
                 cwd=wd, stdout=PIPE, stderr=PIPE)
    _, err = proc.communicate()
    if proc.returncode != 0:
        return False, get_suspected_urls(repo_url, err)
    return True, None

def get_suspected_urls(repo_url, error):
    suspects = []
    for e in error.split('\n'):
        if e == "":
            break
        suspects.append(e)
    return suspects
