from collections import namedtuple
from unittest.mock import call, patch

import pytest

from reconcile.utils.slack_api import SlackApi


@pytest.fixture
def slack_api():
    with patch('reconcile.utils.slack_api.SecretReader', autospec=True) as \
            mock_secret_reader, \
            patch('reconcile.utils.slack_api.SlackClient', autospec=True) as \
            mock_slack_client:

        token = {'path': 'some/path', 'field': 'some-field'}
        slack_api = SlackApi('some-workspace', token)

    SlackApiMock = namedtuple("SlackApiMock", "client mock_secret_reader "
                                              "mock_slack_client")

    return SlackApiMock(slack_api, mock_secret_reader, mock_slack_client)


def test_slack_api__get_default_args_channels(slack_api):
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'channels': [],
        'response_metadata': {
            'next_cursor': ''
        }
    }

    with patch('reconcile.utils.slack_api.SlackApi._get_api_results_limit',
               return_value=500):
        slack_api.client._get('channels')

    assert slack_api.mock_slack_client.return_value.api_call.call_args == \
        call('conversations.list', cursor='', limit=500)


def test_slack_api__get_default_args_users(slack_api):
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'members': [],
        'response_metadata': {
            'next_cursor': ''
        }
    }

    with patch('reconcile.utils.slack_api.SlackApi._get_api_results_limit',
               return_value=500):
        slack_api.client._get('users')

    assert slack_api.mock_slack_client.return_value.api_call.call_args == \
        call('users.list', cursor='', limit=500)


def test_slack_api__get_default_args_unknown_type(slack_api):
    """Leave the limit unset if the resource type is unknown."""
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'something': [],
        'response_metadata': {
            'next_cursor': ''
        }
    }

    with patch('reconcile.utils.slack_api.SlackApi._get_api_results_limit',
               return_value=None):
        slack_api.client._get('something')

    assert slack_api.mock_slack_client.return_value.api_call.call_args == \
        call('something.list', cursor='')


def test_slack_api__get_uses_cache(slack_api):
    """The API is never called when the results are already cached."""
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    slack_api.client.results['channels'] = ['some', 'data']

    assert slack_api.client._get('channels') == ['some', 'data']
    slack_api.mock_slack_client.return_value.api_call.assert_not_called()
