import base64
import tempfile
import re

from subprocess import PIPE, Popen, STDOUT, run

ERR_SPACES = "key has spaces in it"
ERR_EQUAL_SIGNS = "equal signs should only appear at the end of the key"
ERR_BASE64 = "could not perform base64 decode of key"
ERR_ENTRIES = "key must contain both pub and sub entries"


def gpg_key_valid(public_gpg_key):
    stripped_public_gpg_key = public_gpg_key.rstrip()
    if " " in stripped_public_gpg_key:
        raise ValueError(ERR_SPACES)

    equal_sign_count = public_gpg_key.count("=")
    if not stripped_public_gpg_key.endswith("=" * equal_sign_count):
        raise ValueError(ERR_EQUAL_SIGNS)

    try:
        public_gpg_key_dec = base64.b64decode(public_gpg_key)
    except Exception:
        raise ValueError(ERR_BASE64)

    with tempfile.TemporaryDirectory() as gnupg_home_dir:
        # pylint: disable=consider-using-with
        proc = Popen(
            ["gpg", "--homedir", gnupg_home_dir], stdin=PIPE, stdout=PIPE, stderr=STDOUT
        )
        out = proc.communicate(public_gpg_key_dec)
        if proc.returncode != 0:
            raise ValueError(out)

        keys = out[0].decode("utf-8").split("\n")
        key_types = [k.split(" ")[0] for k in keys if k]

    ok = all(elem in key_types for elem in ["pub", "sub"])
    if not ok:
        raise ValueError(ERR_ENTRIES)


def gpg_encrypt(content, public_gpg_key):
    public_gpg_key_dec = base64.b64decode(public_gpg_key)

    with tempfile.TemporaryDirectory() as gnupg_home_dir:
        # import public gpg key
        proc = run(
            ["gpg", "--homedir", gnupg_home_dir, "--import"],
            stdout=PIPE,
            stderr=STDOUT,
            input=public_gpg_key_dec,
            check=True,
        )
        out = proc.stdout.decode("utf-8")
        match = re.search(r"<\S+>", out)
        recipient = match.group(0)[1:-1]
        # encrypt content
        proc = run(
            [
                "gpg",
                "--homedir",
                gnupg_home_dir,
                "--trust-model",
                "always",
                "--encrypt",
                "--armor",
                "-r",
                recipient,
            ],
            input=content.encode(),
            stdout=PIPE,
            stderr=STDOUT,
            check=True,
        )
        out = proc.stdout
    return out.decode("utf-8")
