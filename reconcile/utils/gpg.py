import base64
import re
import tempfile
from subprocess import (
    PIPE,
    STDOUT,
    run,
)


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
