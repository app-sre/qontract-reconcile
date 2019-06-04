import os
import base64

from subprocess import PIPE, Popen, STDOUT


def gpg_key_valid(public_gpg_key):
    DEVNULL = open(os.devnull, 'w')
    try:
        public_gpg_key_dec = base64.b64decode(public_gpg_key)
    except Exception:
        return False
    proc = Popen(['gpg'], stdin=PIPE, stdout=DEVNULL, stderr=STDOUT)
    proc.communicate(public_gpg_key_dec)

    if proc.returncode != 0:
        return False
    return True
