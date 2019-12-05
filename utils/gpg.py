import base64

from subprocess import PIPE, Popen, STDOUT


def gpg_key_valid(public_gpg_key):
    stripped_public_gpg_key = public_gpg_key.rstrip()
    if ' ' in stripped_public_gpg_key:
        return False

    equal_sign_count = public_gpg_key.count('=')
    if not stripped_public_gpg_key.endswith('=' * equal_sign_count):
        return False

    try:
        public_gpg_key_dec = base64.b64decode(public_gpg_key)
    except Exception:
        return False

    proc = Popen(['gpg'], stdin=PIPE, stdout=PIPE, stderr=STDOUT)
    out = proc.communicate(public_gpg_key_dec)
    if proc.returncode != 0:
        return False

    keys = out[0].decode('utf-8').split('\n')
    key_types = [k.split(' ')[0] for k in keys if k]
    ok = all(elem in key_types for elem in ['pub', 'sub'])
    if not ok:
        return False

    return True
