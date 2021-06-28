import base64
import tempfile

from subprocess import PIPE, Popen, STDOUT, run

ERR_SPACES = 'key has spaces in it'
ERR_EQUAL_SIGNS = 'equal signs should only appear at the end of the key'
ERR_BASE64 = 'could not perform base64 decode of key'
ERR_SIGNER = 'key signer dose not match with user org email address '


def gpg_key_valid(public_gpg_key, recipient=None):
    stripped_public_gpg_key = public_gpg_key.rstrip()
    if ' ' in stripped_public_gpg_key:
        msg = ERR_SPACES
        return False, msg

    equal_sign_count = public_gpg_key.count('=')
    if not stripped_public_gpg_key.endswith('=' * equal_sign_count):
        msg = ERR_EQUAL_SIGNS
        return False, msg

    try:
        public_gpg_key_dec = base64.b64decode(public_gpg_key)
    except Exception:
        msg = ERR_BASE64
        return False, msg

    with tempfile.TemporaryDirectory() as gnupg_home_dir:
        proc = Popen(['gpg', '--homedir', gnupg_home_dir],
                     stdin=PIPE,
                     stdout=PIPE,
                     stderr=STDOUT)
        out = proc.communicate(public_gpg_key_dec)
        if proc.returncode != 0:
            return False, out

        if recipient and recipient not in str(out):
            msg = ERR_SIGNER + recipient
            return False, msg

        keys = out[0].decode('utf-8').split('\n')
        key_types = [k.split(' ')[0] for k in keys if k]

    ok = all(elem in key_types for elem in ['pub', 'sub'])
    if not ok:
        msg = 'key must contain both pub and sub entries'
        return False, msg

    return True, ''


def gpg_encrypt(content, recepient, public_gpg_key):
    public_gpg_key_dec = base64.b64decode(public_gpg_key)

    with tempfile.TemporaryDirectory() as gnupg_home_dir:
        # import public gpg key
        proc = run(['gpg', '--homedir', gnupg_home_dir,
                    '--import'],
                   input=public_gpg_key_dec,
                   check=True)
        # encrypt content
        proc = run(['gpg', '--homedir', gnupg_home_dir,
                    '--trust-model', 'always',
                    '--encrypt', '--armor', '-r', recepient],
                   input=content.encode(),
                   stdout=PIPE,
                   stderr=STDOUT,
                   check=True)
        out = proc.stdout
    return out.decode('utf-8')
