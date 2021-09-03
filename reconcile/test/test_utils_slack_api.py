from collections import namedtuple
from unittest.mock import call, patch

import pytest

from reconcile.utils.slack_api import SlackApi, SlackAPIRateLimitedException, \
    SlackAPICallException


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


def test_slack_api_update_usergroup_users_rate_limit_raise(slack_api):
    """Raise an exception when the retry count has been exhausted."""
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'error': 'ratelimited',
        'headers': {
            'retry-after': '5'
        }
    }

    with pytest.raises(SlackAPIRateLimitedException):
        with patch('time.sleep'):
            slack_api.client.update_usergroup_users('ABCD', ['USERA', 'USERB'])

    assert slack_api.mock_slack_client.return_value.api_call.call_count == 5


def test_slack_api_update_usergroup_users_rate_limit_retry(slack_api):
    """
    Retry without raising an exception when rate-limited fewer than the max
    number of retries.
    """
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    rate_limit_response = {
        'error': 'ratelimited',
        'headers': {
            'retry-after': '5'
        }
    }

    # Returns 3 rate-limited responses, and one OK response
    slack_api.mock_slack_client.return_value.api_call.side_effect = [
        rate_limit_response,
        rate_limit_response,
        rate_limit_response,
        {'ok': 'true'}
    ]

    with patch('time.sleep'):
        slack_api.client.update_usergroup_users('ABCD', ['USERA', 'USERB'])

    assert slack_api.mock_slack_client.return_value.api_call.call_count == 4


def test_slack_api_update_usergroup_users_raise_for_errors(slack_api):
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'error': 'some_unknown_error',
    }

    with pytest.raises(SlackAPICallException):
        with patch('time.sleep'):
            slack_api.client.update_usergroup_users('ABCD', ['USERA', 'USERB'])


def test_slack_api_update_usergroup_users_invalid_users(slack_api):
    """
    Don't raise an exception when Slack returns an 'invalid_users' error
    because it will still empty groups as expected.
    """
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'error': 'invalid_users',
    }

    with patch('time.sleep'):
        slack_api.client.update_usergroup_users('ABCD', ['USERA', 'USERB'])


def test_slack_api_update_usergroup_rate_limit_raise(slack_api):
    """Raise an exception when the retry count has been exhausted."""
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'error': 'ratelimited',
        'headers': {
            'retry-after': '5'
        }
    }

    with pytest.raises(SlackAPIRateLimitedException):
        with patch('time.sleep'):
            slack_api.client.update_usergroup('ABCD', ['CHANA', 'CHANB'],
                                              'Some description')

    assert slack_api.mock_slack_client.return_value.api_call.call_count == 5


def test_slack_api_update_usergroup_rate_limit_retry(slack_api):
    """
    Retry without raising an exception when rate-limited fewer than the max
    number of retries.
    """
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    rate_limit_response = {
        'error': 'ratelimited',
        'headers': {
            'retry-after': '5'
        }
    }

    # Returns 3 rate-limited responses, and one OK response
    slack_api.mock_slack_client.return_value.api_call.side_effect = [
        rate_limit_response,
        rate_limit_response,
        rate_limit_response,
        {'ok': 'true'}
    ]

    with patch('time.sleep'):
        slack_api.client.update_usergroup('ABCD', ['CHANA', 'CHANB'],
                                          'Some description')

    assert slack_api.mock_slack_client.return_value.api_call.call_count == 4


def test_slack_api_update_usergroup_raise_for_errors(slack_api):
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'error': 'some_unknown_error',
    }

    with pytest.raises(SlackAPICallException):
        with patch('time.sleep'):
            slack_api.client.update_usergroup('ABCD', ['CHANA', 'CHANB'],
                                              'Some description')
