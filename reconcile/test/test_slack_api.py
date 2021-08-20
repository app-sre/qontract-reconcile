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


def test_slack_api__get_uses_kwargs_properly(slack_api):
    """Ensure that _get() properly passes along kwargs to the SC API client."""
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'channels': [],
        'response_metadata': {
            'next_cursor': ''
        }
    }

    slack_api.client._get('channels', limit=1000)

    assert slack_api.mock_slack_client.return_value.api_call.call_args == \
        call('conversations.list', cursor='', limit=1000)


def test_slack_api__get_uses_cache(slack_api):
    """The API is never called when the results are already cached."""
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    slack_api.client.results['channels'] = ['some', 'data']

    assert slack_api.client._get('channels') == ['some', 'data']
    slack_api.mock_slack_client.return_value.api_call.assert_not_called()
