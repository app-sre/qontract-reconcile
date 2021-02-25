from unittest import mock

from pytest import raises
import requests

from reconcile.utils.qontract_server_client import QontractServerClient


def mocked_requests_get(*args, **kwargs):
    class MockResponse:
        def __init__(self, content):
            self.content = content.encode('utf-8')

        def raise_for_status(self):
            pass

    if args[0] == 'https://example.com/sha256':
        return MockResponse("abcdef")

    return MockResponse('')


def mocked_requests_post(*args, **kwargs):
    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return '{}'

    return MockResponse()


class TestQontractServerClient:
    @staticmethod
    @mock.patch('requests.get', side_effect=mocked_requests_get)
    def test_get_sha(mock_get):
        client = QontractServerClient('https://example.com/graphql')
        assert client.get_sha() == 'abcdef'

    @staticmethod
    @mock.patch('requests.post', side_effect=mocked_requests_post)
    def test_query(mock_post):
        client = QontractServerClient('https://example.com/graphql')
        client.query('TESTQUERY')
        first_call = mock_post.call_args_list[0]
        assert first_call.args[0] == 'https://example.com/graphql'

    @staticmethod
    @mock.patch('requests.post', side_effect=mocked_requests_post)
    def test_query_token(mock_post):
        client = QontractServerClient(
            'https://example.com/graphql', token="mytoken")
        client.query('TESTQUERY')
        first_call = mock_post.call_args_list[0]
        assert first_call.kwargs['headers']['Authorization'] == 'mytoken'

    @staticmethod
    @mock.patch('requests.sessions.Session.post',
                side_effect=mocked_requests_post)
    def test_query_session(mock_post):
        client = QontractServerClient('https://example.com/graphql',
                                      use_sessions=True)
        client.query('TESTQUERY')
        first_call = mock_post.call_args_list[0]
        assert first_call.args[0] == 'https://example.com/graphql'

    @staticmethod
    @mock.patch('requests.get', side_effect=mocked_requests_get)
    @mock.patch('requests.post', side_effect=mocked_requests_post)
    def test_query_sha(mock_post, mock_get):
        client = QontractServerClient('https://example.com/graphql',
                                      sha_url=True)
        client.query('TESTQUERY')
        first_call = mock_post.call_args_list[0]
        assert first_call.args[0] == 'https://example.com/graphqlsha/abcdef'

    @staticmethod
    def test_query_raises():
        client = QontractServerClient('https://example.com/graphql')
        with raises(requests.exceptions.RequestException):
            client.query('TESTQUERY')
