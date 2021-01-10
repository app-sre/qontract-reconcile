import base64
import tempfile
import shutil

from subprocess import PIPE, Popen, STDOUT

from utils.defer import defer


@defer
def gpg_key_valid(public_gpg_key, defer=None):
    stripped_public_gpg_key = public_gpg_key.rstrip()
    if ' ' in stripped_public_gpg_key:
        msg = 'key has spaces in it'
        return False, msg

    equal_sign_count = public_gpg_key.count('=')
    if not stripped_public_gpg_key.endswith('=' * equal_sign_count):
        msg = 'equal signs should only appear at the end of the key'
        return False, msg

    try:
        public_gpg_key_dec = base64.b64decode(public_gpg_key)
    except Exception:
        msg = 'could not perform base64 decode of key'
        return False, msg

    gnupg_home_dir = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(gnupg_home_dir))
    proc = Popen(['gpg', '--homedir', gnupg_home_dir],
                 stdin=PIPE,
                 stdout=PIPE,
                 stderr=STDOUT)
    out = proc.communicate(public_gpg_key_dec)
    if proc.returncode != 0:
        return False, out

    keys = out[0].decode('utf-8').split('\n')
    key_types = [k.split(' ')[0] for k in keys if k]
    ok = all(elem in key_types for elem in ['pub', 'sub'])
    if not ok:
        msg = 'key must contain both pub and sub entries'
        return False, msg

    return True, ''


@defer
def gpg_encrypt(content, recepient, public_gpg_key, defer=None):
    public_gpg_key_dec = base64.b64decode(public_gpg_key)

    gnupg_home_dir = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(gnupg_home_dir))
    # import public gpg key
    proc = Popen(['gpg', '--homedir', gnupg_home_dir,
                  '--import'],
                 stdin=PIPE,
                 stdout=PIPE,
                 stderr=STDOUT)
    out = proc.communicate(public_gpg_key_dec)
    if proc.returncode != 0:
        return None
    # encrypt content
    proc = Popen(['gpg', '--homedir', gnupg_home_dir,
                  '--trust-model', 'always',
                  '--encrypt', '--armor', '-r', recepient],
                 stdin=PIPE,
                 stdout=PIPE,
                 stderr=STDOUT)
    out = proc.communicate(content.encode())
    if proc.returncode != 0:
        return None

    return out[0].decode('utf-8')
