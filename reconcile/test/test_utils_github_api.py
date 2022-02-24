from unittest import TestCase
from unittest.mock import patch
from requests.exceptions import ConnectTimeout
from reconcile.utils.github_api import GithubApi


class TestGithubApi(TestCase):
    @patch("reconcile.utils.github_api.GH_BASE_URL", "http://198.18.0.1")
    @patch("reconcile.utils.github_api.SecretReader", autospec=True)
    def test_github_client_timeout(self, secret_reader_mock):
        secret_reader_mock.return_value.read.return_value = "0000000"
        instance = {
            "token": "non-existent-token",
        }
        with self.assertRaises(ConnectTimeout):
            GithubApi(instance, repo_url="repo", settings=None, timeout=1)
