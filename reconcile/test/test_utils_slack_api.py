import json
from collections import namedtuple
from unittest.mock import call, patch

import httpretty
import pytest
from slack_sdk.errors import SlackApiError

import reconcile
from reconcile.utils.slack_api import SlackApi, MAX_RETRIES, \
    UserNotFoundException


@pytest.fixture
def slack_api(mocker):
    mock_secret_reader = mocker.patch.object(
        reconcile.utils.slack_api, 'SecretReader', autospec=True)

    mock_slack_client = mocker.patch.object(
        reconcile.utils.slack_api, 'WebClient', autospec=True)

    # autospec doesn't know about instance attributes
    mock_slack_client.return_value.retry_handlers = []

    token = {'path': 'some/path', 'field': 'some-field'}
    slack_api = SlackApi('some-workspace', token)

    SlackApiMock = namedtuple("SlackApiMock", "client mock_secret_reader "
                                              "mock_slack_client")

    return SlackApiMock(slack_api, mock_secret_reader, mock_slack_client)


def test__get_default_args_channels(slack_api):
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
        call('conversations.list', http_verb='GET',
             params={'limit': 500, 'cursor': ''})


def test__get_default_args_users(slack_api):
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
        call('users.list', http_verb='GET',
             params={'limit': 500, 'cursor': ''})


def test__get_default_args_unknown_type(slack_api):
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
        call('something.list', http_verb='GET', params={'cursor': ''})


def test__get_uses_cache(slack_api):
    """The API is never called when the results are already cached."""
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    slack_api.client._results['channels'] = ['some', 'data']

    assert slack_api.client._get('channels') == ['some', 'data']
    slack_api.mock_slack_client.return_value.api_call.assert_not_called()


def test_chat_post_message(slack_api):
    """Don't raise an exception when the channel is set."""
    slack_api.client.channel = 'some-channel'
    slack_api.client.chat_post_message('test')


def test_chat_post_message_missing_channel(slack_api):
    """Raises an exception when channel isn't set."""
    slack_api.client.channel = None
    with pytest.raises(ValueError):
        slack_api.client.chat_post_message('test')


def test_update_usergroup_users(slack_api):
    slack_api.client.update_usergroup_users('ABCD', ['USERA', 'USERB'])

    assert slack_api.mock_slack_client.return_value\
        .usergroups_users_update.call_args == \
           call(usergroup='ABCD', users=['USERA', 'USERB'])


@patch.object(SlackApi, 'get_random_deleted_user', autospec=True)
def test_update_usergroup_users_empty_list(mock_get_deleted, slack_api):
    """Passing in an empty list supports removing all users from a group."""
    mock_get_deleted.return_value = 'a-deleted-user'

    slack_api.client.update_usergroup_users('ABCD', [])

    assert slack_api.mock_slack_client.return_value\
        .usergroups_users_update.call_args == \
           call(usergroup='ABCD', users=['a-deleted-user'])


@patch('reconcile.utils.slack_api.get_config', autospec=True)
def test_get_user_id_by_name_user_not_found(get_config_mock, slack_api):
    """
    Check that UserNotFoundException will be raised under expected conditions.
    """
    get_config_mock.return_value = {'smtp': {'mail_address': 'redhat.com'}}
    slack_api.mock_slack_client.return_value\
        .users_lookupByEmail.side_effect = \
        SlackApiError('Some error message', {'error': 'users_not_found'})

    with pytest.raises(UserNotFoundException):
        slack_api.client.get_user_id_by_name('someuser')


@patch('reconcile.utils.slack_api.get_config', autospec=True)
def test_get_user_id_by_name_reraise(get_config_mock, slack_api):
    """
    Check that SlackApiError is re-raised when not otherwise handled as a user
    not found error.
    """
    get_config_mock.return_value = {'smtp': {'mail_address': 'redhat.com'}}
    slack_api.mock_slack_client.return_value\
        .users_lookupByEmail.side_effect = \
        SlackApiError('Some error message', {'error': 'internal_error'})

    with pytest.raises(SlackApiError):
        slack_api.client.get_user_id_by_name('someuser')

#
# Slack WebClient retry tests
#
# These tests are meant to ensure that the built-in retry functionality is
# working as expected in the Slack WebClient. This provides some verification
# that the handlers are configured properly, as well as testing the custom
# ServerErrorRetryHandler handler.
#


@httpretty.activate(allow_net_connect=False)
@patch('reconcile.utils.slack_api.SecretReader', autospec=True)
@patch('time.sleep', autospec=True)
def test_slack_api__client_throttle_raise(mock_sleep, mock_secret_reader):
    """Raise an exception if the max retries is exceeded."""
    httpretty.register_uri(
        httpretty.POST,
        'https://www.slack.com/api/users.list',
        adding_headers={'Retry-After': '1'},
        body=json.dumps({'ok': 'false', 'error': 'ratelimited'}),
        status=429
    )

    slack_client = SlackApi(
        'workspace', {'path': 'some/path', 'field': 'some-field'},
        init_usergroups=False
    )

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == MAX_RETRIES + 1


@httpretty.activate(allow_net_connect=False)
@patch('reconcile.utils.slack_api.SecretReader', autospec=True)
@patch('time.sleep', autospec=True)
def test_slack_api__client_throttle_doesnt_raise(mock_sleep,
                                                 mock_secret_reader):
    """Don't raise an exception if the max retries aren't reached."""
    uri_args = (httpretty.POST, 'https://www.slack.com/api/users.list')
    uri_kwargs_failure = {
        'adding_headers': {'Retry-After': '1'},
        'body': json.dumps({'ok': 'false', 'error': 'ratelimited'}),
        'status': 429
    }
    uri_kwargs_success = {
        'body': json.dumps({'ok': 'true'}),
        'status': 200
    }

    # These are registered LIFO (3 failures and then 1 success)
    httpretty.register_uri(*uri_args, **uri_kwargs_success)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)

    slack_client = SlackApi(
        'workspace', {'path': 'some/path', 'field': 'some-field'},
        init_usergroups=False
    )

    slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == 4


@httpretty.activate(allow_net_connect=False)
@patch('reconcile.utils.slack_api.SecretReader', autospec=True)
@patch('time.sleep', autospec=True)
def test_slack_api__client_5xx_raise(mock_sleep, mock_secret_reader):
    """Raise an exception if the max retries is exceeded."""
    httpretty.register_uri(
        httpretty.POST,
        'https://www.slack.com/api/users.list',
        body=json.dumps({'ok': 'false', 'error': 'internal_error'}),
        status=500
    )

    slack_client = SlackApi(
        'workspace', {'path': 'some/path', 'field': 'some-field'},
        init_usergroups=False
    )

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == MAX_RETRIES + 1


@httpretty.activate(allow_net_connect=False)
@patch('reconcile.utils.slack_api.SecretReader', autospec=True)
@patch('time.sleep', autospec=True)
def test_slack_api__client_5xx_doesnt_raise(mock_sleep, mock_secret_reader):
    """Don't raise an exception if the max retries aren't reached."""
    uri_args = (httpretty.POST, 'https://www.slack.com/api/users.list')
    uri_kwargs_failure = {
        'body': json.dumps({'ok': 'false', 'error': 'internal_error'}),
        'status': 500
    }
    uri_kwargs_success = {
        'body': json.dumps({'ok': 'true'}),
        'status': 200
    }

    # These are registered LIFO (3 failures and then 1 success)
    httpretty.register_uri(*uri_args, **uri_kwargs_success)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)

    slack_client = SlackApi(
        'workspace', {'path': 'some/path', 'field': 'some-field'},
        init_usergroups=False
    )

    slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == 4


@httpretty.activate(allow_net_connect=False)
@patch('reconcile.utils.slack_api.SecretReader', autospec=True)
@patch('time.sleep', autospec=True)
def test_slack_api__client_dont_retry(mock_sleep, mock_secret_reader):
    """Don't retry client-side errors that aren't 429s."""
    httpretty.register_uri(
        httpretty.POST,
        'https://www.slack.com/api/users.list',
        body=json.dumps({'ok': 'false', 'error': 'internal_error'}),
        status=401
    )

    slack_client = SlackApi(
        'workspace', {'path': 'some/path', 'field': 'some-field'},
        init_usergroups=False
    )

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == 1
