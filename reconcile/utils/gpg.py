import base64
import re
import tempfile
from subprocess import (
    PIPE,
    STDOUT,
    run,
)


def gpg_encrypt(content: str, public_gpg_key: str) -> str:
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
        if not match:
            raise ValueError("No recipient found in GPG import output")
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
        encrypted_out = proc.stdout
    return encrypted_out.decode("utf-8")
