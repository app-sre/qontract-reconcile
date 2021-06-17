from unittest import TestCase
from unittest.mock import patch

import reconcile.utils.gpg as gpg


class TestGpgKeyValid(TestCase):
    def test_gpg_key_invalid_spaces(self):
        key = 'key with spaces'
        valid, msg = gpg.gpg_key_valid(key)
        self.assertFalse(valid)
        self.assertEqual(msg, gpg.ERR_SPACES)

    def test_gpg_key_invalid_equal_signs(self):
        key = 'equal=signs=not=at=end=of=key'
        valid, msg = gpg.gpg_key_valid(key)
        self.assertFalse(valid)
        self.assertEqual(msg, gpg.ERR_EQUAL_SIGNS)

    def test_gpg_key_invalid_base64(self):
        # $ echo -n "hello world" | base64
        # aGVsbG8gd29ybGQ=
        key = 'aGVsbG8gd29ybGQ'
        valid, msg = gpg.gpg_key_valid(key)
        self.assertFalse(valid)
        self.assertEqual(msg, gpg.ERR_BASE64)


# We have to mangle the namespace of the gpg module, since it imports
# Popen. Had that module chosen "import subprocess;
# subprocess.Popen(...)" we'd be patching subprocess instead.
@patch.object(gpg, 'run')
class TestGpgEncrypt(TestCase):
    def test_gpg_encrypt_all_ok(self, popen):
        popen.return_value.communicate.return_value = (b"stdout", b"stderr")

        self.assertEqual(gpg.gpg_encrypt('acontent', 'arecipient', 'akey'),
                         'stdout')
