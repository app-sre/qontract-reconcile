import json
from collections import namedtuple
from typing import Union, Dict
from unittest.mock import call, patch, MagicMock

import httpretty
import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

import reconcile
from reconcile.utils.slack_api import SlackApi, \
    UserNotFoundException, SlackApiConfig, UsergroupNotFoundException


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


@pytest.fixture()
def _get_channels_default(mocker):
    return mocker.patch('reconcile.utils.slack_api.SlackApi._get_channels',
                        return_value={'c1': {'name': 'channel1'},
                                      'c2': {'name': 'channel2'}}.items())


@pytest.fixture()
def _get_users_default(mocker):
    return mocker.patch('reconcile.utils.slack_api.SlackApi._get_users',
                        return_value={
                            'u1': {'name': 'user1', 'deleted': False},
                            'u2': {'name': 'user2', 'deleted': True}}.items())


@pytest.fixture()
def _get_users_no_deleted(mocker):
    return mocker.patch('reconcile.utils.slack_api.SlackApi._get_users',
                        return_value={
                            'u': {'name': 'user2', 'deleted': False}}.items())


def test_slack_api_config_defaults():
    slack_api_config = SlackApiConfig()

    assert slack_api_config.max_retries == SlackApiConfig.MAX_RETRIES
    assert slack_api_config.timeout == SlackApiConfig.TIMEOUT


def test_slack_api_config_from_dict():
    data = {
        'global': {
            'max_retries': 1,
            'timeout': 5
        },
        'methods': [
            {'name': 'users.list', 'args': "{\"limit\":1000}"},
            {'name': 'conversations.list', 'args': "{\"limit\":500}"}
        ]
    }

    slack_api_config = SlackApiConfig.from_dict(data)

    assert isinstance(slack_api_config, SlackApiConfig)

    assert slack_api_config.get_method_config('users.list') == {'limit': 1000}
    assert slack_api_config.get_method_config('conversations.list') == \
           {'limit': 500}
    assert slack_api_config.get_method_config('doesntexist') is None

    assert slack_api_config.max_retries == 1
    assert slack_api_config.timeout == 5


def new_slack_response(data: Dict[str, Union[bool, str]]):
    return SlackResponse(client='', http_verb='', api_url='',
                         req_args={}, data=data, headers={},
                         status_code=0)


def test_instantiate_slack_api_with_config(mocker):
    """
    When SlackApiConfig is passed into SlackApi, the constructor shouldn't
    create a default configuration object.
    """
    mocker.patch.object(
        reconcile.utils.slack_api, 'SecretReader', autospec=True)

    mock_slack_client = mocker.patch.object(
        reconcile.utils.slack_api, 'WebClient', autospec=True)

    # autospec doesn't know about instance attributes
    mock_slack_client.return_value.retry_handlers = []

    config = SlackApiConfig()

    token = {'path': 'some/path', 'field': 'some-field'}
    slack_api = SlackApi('some-workspace', token, config)

    assert slack_api.api_config is config


def test__resource_get_or_cached_default_args(mocker, slack_api):
    mock_get = mocker.patch(
        'reconcile.utils.slack_api.SlackApi._paginated_get', return_value={})

    slack_api.client._resource_get_or_cached(
        SlackApi.RESOURCE_GET_CONVERSATIONS)

    assert mock_get.call_args == call(SlackApi.RESOURCE_GET_CONVERSATIONS,
                                      {'cursor': ''})


def test__resource_get_or_cached_with_config(mocker, slack_api):
    mock_get = mocker.patch(
        'reconcile.utils.slack_api.SlackApi._paginated_get', return_value={})

    api_config = SlackApiConfig()
    api_config.set_method_config('conversations.list', {'limit': 500})
    slack_api.client.api_config = api_config

    slack_api.client._resource_get_or_cached(
        SlackApi.RESOURCE_GET_CONVERSATIONS)

    assert mock_get.call_args == call(SlackApi.RESOURCE_GET_CONVERSATIONS,
                                      {'cursor': '', 'limit': 500})


def test__resource_get_or_cached_with_other_config(mocker, slack_api):
    mock_get = mocker.patch(
        'reconcile.utils.slack_api.SlackApi._paginated_get', return_value={})

    api_config = SlackApiConfig()
    api_config.set_method_config('conversations.list', {'limit': 500})
    slack_api.client.api_config = api_config

    slack_api.client._resource_get_or_cached('something')

    assert mock_get.call_args == call('something', {'cursor': ''})


def test__resource_get_or_cached_uses_cache(mocker, slack_api):
    """The API is never called when the results are already cached."""
    mock_get = mocker.patch(
        'reconcile.utils.slack_api.SlackApi._paginated_get', return_value={})

    slack_api.client._cached_results['channels'] = ['some', 'data']

    assert slack_api.client._resource_get_or_cached('channels') == ['some',
                                                                    'data']
    mock_get.assert_not_called()


def test__paginated_get_default(slack_api):
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        'channels': [{'id': 'c1'}],
        'response_metadata': {
            'next_cursor': ''
        }
    }

    api_config = SlackApiConfig()
    api_config.set_method_config('conversations.list', {'limit': 500})
    slack_api.client.api_config = api_config

    c = slack_api.client._paginated_get(
        SlackApi.RESOURCE_GET_CONVERSATIONS, {'cursor': ''})

    assert slack_api.mock_slack_client.return_value.api_call.call_args == \
           call('conversations.list', http_verb='GET', params={'cursor': ''})
    assert c['c1'] == {'id': 'c1'}


def test__paginated_get_paginated(slack_api):
    slack_api.mock_slack_client.return_value.api_call.side_effect = [{
        'channels': [{'id': '1'}],
        'response_metadata': {'next_cursor': 'foo'}},
        {'channels': [{'id': '2'}], 'response_metadata': {'next_cursor': ''}}]

    c = slack_api.client._paginated_get(
        SlackApi.RESOURCE_GET_CONVERSATIONS, {'cursor': ''})

    assert slack_api.mock_slack_client.return_value.api_call.call_count == 2
    assert c['1'] == {'id': '1'}
    assert c['2'] == {'id': '2'}


def test_chat_post_message(slack_api):
    """Don't raise an exception when the channel is set."""
    slack_api.client.channel = 'some-channel'
    slack_api.client.chat_post_message('test')


def test_chat_post_message_missing_channel(slack_api):
    """Raises an exception when channel isn't set."""
    slack_api.client.channel = None
    with pytest.raises(ValueError):
        slack_api.client.chat_post_message('test')


def test_chat_post_message_channel_not_found(mocker, slack_api):
    slack_api.client.channel = 'test'
    mock_join = mocker.patch('reconcile.utils.slack_api.SlackApi.join_channel',
                             autospec=True)
    nf_resp = new_slack_response({'ok': False, 'error': 'not_in_channel'})
    slack_api.mock_slack_client.return_value.chat_postMessage.side_effect = \
        [SlackApiError('error', nf_resp), None]
    slack_api.client.chat_post_message('foo')
    assert slack_api.mock_slack_client.return_value.chat_postMessage. \
           call_count == 2
    mock_join.assert_called_once()


def test_chat_post_message_ok(slack_api):
    slack_api.client.channel = 'test'
    ok_resp = new_slack_response({'ok': True})
    slack_api.mock_slack_client.return_value.chat_postMessage.side_effect = \
        ok_resp
    slack_api.client.chat_post_message('foo')
    slack_api.mock_slack_client.return_value.chat_postMessage. \
        assert_called_once()


def test_chat_post_message_raises_other(mocker, slack_api):
    slack_api.client.channel = 'test'
    err_resp = new_slack_response({'ok': False, 'error': 'no_text'})
    slack_api.mock_slack_client.return_value.chat_postMessage.side_effect = \
        SlackApiError('error', err_resp)
    with pytest.raises(SlackApiError):
        slack_api.client.chat_post_message('foo')
    slack_api.mock_slack_client.return_value.chat_postMessage. \
        assert_called_once()


def test_validate_result_key_dict():
    resource_keys = [k for k in SlackApi.__dict__ if k.startswith(
        'RESOURCE_GET') and k != 'RESOURCE_GET_RESULT_KEYS']

    for key in resource_keys:
        assert getattr(SlackApi, key) in SlackApi.RESOURCE_GET_RESULT_KEYS


def test_get_usergroup_id(mocker, slack_api):
    mock = mocker.patch('reconcile.utils.slack_api.SlackApi.get_usergroup',
                        return_value={'id': 'foo', 'handle': 'oof'})

    a = slack_api.client.get_usergroup_id('oof')
    assert a == 'foo'
    mock.assert_called_with('oof')


def test_get_usergroup(mocker, slack_api):
    returned_groups = {'foo': {'id': 'foo', 'handle': 'h1'},
                       'oof': {'id': 'oof', 'handle': 'h2'}}

    mock = mocker.patch(
        'reconcile.utils.slack_api.SlackApi._resource_get_or_cached',
        return_value=returned_groups)

    u = slack_api.client.get_usergroup('h2')
    assert u['id'] == 'oof'
    mock.assert_called_with(SlackApi.RESOURCE_GET_USERGROUPS)


def test_get_usergroup_failed(mocker, slack_api):
    returned_groups = {'foo': {'id': 'foo', 'handle': 'h1'}}

    mocker.patch('reconcile.utils.slack_api.SlackApi._resource_get_or_cached',
                 return_value=returned_groups)

    with pytest.raises(UsergroupNotFoundException):
        slack_api.client.get_usergroup('h2')


def test_describe_usergroup(mocker, slack_api):
    mgroup = mocker.patch('reconcile.utils.slack_api.SlackApi.get_usergroup',
                          return_value={'description': 'a',
                                        'users': ['u1'],
                                        'prefs': {'channels': ['c']}})

    muser = mocker.patch('reconcile.utils.slack_api.SlackApi.get_users_by_ids',
                         return_value={'u1': 'a'})

    mchan = mocker.patch(
        'reconcile.utils.slack_api.SlackApi.get_channels_by_ids',
        return_value={'c': 'name'})
    u, c, d = slack_api.client.describe_usergroup('handle')
    assert u == {'u1': 'a'}
    muser.assert_called_once_with(['u1'])
    assert c == {'c': 'name'}
    mchan.assert_called_once_with(['c'])
    assert d == 'a'
    mgroup.assert_called_once_with('handle')


def test_get_channels_by_names(_get_channels_default, slack_api):
    c = slack_api.client.get_channels_by_names('channel2')
    assert len(c) == 1
    assert c['c2'] == 'channel2'
    c = slack_api.client.get_channels_by_names(['channel1', 'channel2'])
    assert len(c) == 2
    assert 'c2' in c and 'c1' in c


def test_get_channels_by_ids(_get_channels_default, slack_api):
    c = slack_api.client.get_channels_by_ids('c2')
    assert len(c) == 1
    assert c['c2'] == 'channel2'
    c = slack_api.client.get_channels_by_ids(['c1', 'c2'])
    assert len(c) == 2
    assert 'c2' in c and 'c1' in c


def test_get_users_by_names(_get_users_default, slack_api):
    u = slack_api.client.get_users_by_names('user2')
    assert len(u) == 1
    assert u['u2'] == 'user2'
    u = slack_api.client.get_users_by_names(['user1', 'user2'])
    assert len(u) == 2
    assert 'u1' in u and 'u2' in u


def test_get_users_by_ids(_get_users_default, slack_api):
    u = slack_api.client.get_users_by_ids('u2')
    assert len(u) == 1
    assert u['u2'] == 'user2'
    u = slack_api.client.get_users_by_ids(['u1', 'u2'])
    assert len(u) == 2
    assert 'u1' in u and 'u2' in u


def test_get_random_user(_get_users_default, slack_api):
    u = slack_api.client.get_random_deleted_user()
    assert u == 'u2'


def test_get_random_user_not_found(_get_users_no_deleted, mocker, slack_api):
    log_mock = mocker.patch('logging.error')
    u = slack_api.client.get_random_deleted_user()
    assert u == ''
    log_mock.assert_called_once()


def test_join_channel_missing_channel(slack_api):
    """Raises an exception when the channel is not set."""
    slack_api.client.channel = None
    with pytest.raises(ValueError):
        slack_api.client.join_channel()


@pytest.mark.parametrize("joined", [True, False])
def test_join_channel_already_joined(slack_api, mocker, joined):
    mocker.patch('reconcile.utils.slack_api.SlackApi.get_channels_by_names',
                 return_value={'123': 'test', '456': 'foo'})
    slack_api.client.channel = 'test'
    slack_response = MagicMock(SlackResponse)
    slack_response.data = {'channel': {'is_member': joined}}
    slack_api.mock_slack_client.return_value.conversations_info. \
        return_value = slack_response
    slack_api.mock_slack_client.return_value.conversations_join. \
        return_value = None
    slack_api.client.join_channel()
    slack_api.mock_slack_client.return_value.conversations_info. \
        assert_called_once_with(channel='123')
    if joined:
        slack_api.mock_slack_client.return_value.conversations_join. \
            assert_not_called()
    else:
        slack_api.mock_slack_client.return_value.conversations_join. \
            assert_called_once_with(channel='123')


def test_update_usergroup_users(slack_api):
    slack_api.client.update_usergroup_users('ABCD', ['USERA', 'USERB'])

    assert slack_api.mock_slack_client.return_value \
           .usergroups_users_update.call_args == \
           call(usergroup='ABCD', users=['USERA', 'USERB'])


@patch.object(SlackApi, 'get_random_deleted_user', autospec=True)
def test_update_usergroup_users_empty_list(mock_get_deleted, slack_api):
    """Passing in an empty list supports removing all users from a group."""
    mock_get_deleted.return_value = 'a-deleted-user'

    slack_api.client.update_usergroup_users('ABCD', [])

    assert slack_api.mock_slack_client.return_value \
           .usergroups_users_update.call_args == \
           call(usergroup='ABCD', users=['a-deleted-user'])


def test_get_user_id_by_name_user_not_found(slack_api):
    """
    Check that UserNotFoundException will be raised under expected conditions.
    """
    slack_api.mock_slack_client.return_value\
        .users_lookupByEmail.side_effect = \
        SlackApiError('Some error message', {'error': 'users_not_found'})

    with pytest.raises(UserNotFoundException):
        slack_api.client.get_user_id_by_name('someuser', 'redhat.com')


def test_get_user_id_by_name_reraise(slack_api):
    """
    Check that SlackApiError is re-raised when not otherwise handled as a user
    not found error.
    """
    slack_api.mock_slack_client.return_value\
        .users_lookupByEmail.side_effect = \
        SlackApiError('Some error message', {'error': 'internal_error'})

    with pytest.raises(SlackApiError):
        slack_api.client.get_user_id_by_name('someuser', 'redhat.com')


def test_update_usergroups_users_empty_no_raise(mocker, slack_api):
    """
    invalid_users errors shouldn't be raised because providing an empty
    list is actually removing users from the usergroup.
    """
    mocker.patch.object(SlackApi, 'get_random_deleted_user', autospec=True)

    slack_api.mock_slack_client.return_value.usergroups_users_update \
        .side_effect = SlackApiError('Some error message',
                                     {'error': 'invalid_users'})

    slack_api.client.update_usergroup_users('ABCD', [])


def test_update_usergroups_users_raise(slack_api):
    """
    Any errors other than invalid_users should result in an exception being
    raised.
    """
    slack_api.mock_slack_client.return_value.usergroups_users_update \
        .side_effect = SlackApiError('Some error message',
                                     {'error': 'internal_error'})

    with pytest.raises(SlackApiError):
        slack_api.client.update_usergroup_users('ABCD', ['USERA'])


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
        'workspace',
        {'path': 'some/path', 'field': 'some-field'},
    )

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == SlackApiConfig.MAX_RETRIES + 1


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
        'workspace', {'path': 'some/path', 'field': 'some-field'}
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
        'workspace', {'path': 'some/path', 'field': 'some-field'})

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == SlackApiConfig.MAX_RETRIES + 1


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
        'workspace', {'path': 'some/path', 'field': 'some-field'})

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
        'workspace', {'path': 'some/path', 'field': 'some-field'})

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call('users.list')

    assert len(httpretty.latest_requests()) == 1
