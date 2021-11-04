from unittest import TestCase
from unittest.mock import patch
from requests.exceptions import ConnectTimeout
from reconcile.utils.gitlab_api import GitLabApi


class TestGitlabApi(TestCase):

    def test_gitlab_client_timeout(self):
        with patch('reconcile.utils.gitlab_api.SecretReader', autospec=True) \
          as secret_reader_mock:
            secret_reader_mock.return_value.read.return_value = "0000000"
            instance = {
                "url": "http://10.255.255.1",  # Non routable ip address
                "token": "non-existent-token",
                "sslVerify": False
            }
            with self.assertRaises(ConnectTimeout):
                GitLabApi(instance, timeout=1)
