import copy
from unittest.mock import create_autospec, call

import pytest

from reconcile.slack_usergroups import act
from reconcile.utils.slack_api import SlackApi


@pytest.fixture
def base_state():
    desired_state = {
        'slack-workspace': {
            'usergroup-1': {
                'workspace': 'slack-workspace',
                'usergroup': 'usergroup-1',
                'usergroup_id': 'USERGA',
                'users': {'USERA': 'username'},
                'channels': {'CHANA': 'channel'},
                'description': 'Some description'
            }
        }
    }

    return desired_state


def test_act_no_changes_detected(base_state):
    """No changes should be made when the states are identical."""

    current_state = base_state
    desired_state = base_state

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    slack_client_mock.update_usergroup.assert_not_called()
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_dryrun_no_changes_made(base_state):
    """No changes should be made when dryrun mode is enabled."""

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state['slack-workspace']['usergroup-1']['users'] = {
        'USERB': 'someotherusername'
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=True)

    slack_client_mock.update_usergroup.assert_not_called()
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_empty_current_state(base_state):
    """
    An empty current state should be able to be handled properly (watching for
    TypeErrors, etc).
    """

    current_state = {}
    desired_state = base_state

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call('USERGA', ['CHANA'], 'Some description')
    ]
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call('USERGA', ['USERA'])
    ]


def test_act_update_usergroup_users(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state['slack-workspace']['usergroup-1']['users'] = {
        'USERB': 'someotherusername', 'USERC': 'anotheruser'
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    slack_client_mock.update_usergroup.assert_not_called()
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call('USERGA', ['USERB', 'USERC'])
    ]


def test_act_update_usergroup_channels(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state['slack-workspace']['usergroup-1']['channels'] = {
        'CHANB': 'someotherchannel'
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call('USERGA', ['CHANB'], 'Some description')
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_update_usergroup_description(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state['slack-workspace']['usergroup-1']['description'] = \
        'A different description'

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call('USERGA', ['CHANA'], 'A different description')
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_update_usergroup_desc_and_channels(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state['slack-workspace']['usergroup-1']['description'] = \
        'A different description'
    desired_state['slack-workspace']['usergroup-1']['channels'] = {
        'CHANB': 'someotherchannel'
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call('USERGA', ['CHANB'], 'A different description')
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_add_new_usergroups(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state['slack-workspace'].update({
        'usergroup-2': {
            'workspace': 'slack-workspace',
            'usergroup': 'usergroup-2',
            'usergroup_id': 'USERGB',
            'users': {'USERB': 'userb', 'USERC': 'userc'},
            'channels': {'CHANB': 'channelb', 'CHANC': 'channelc'},
            'description': 'A new usergroup'
        }
    })

    desired_state['slack-workspace'].update({
        'usergroup-3': {
            'workspace': 'slack-workspace',
            'usergroup': 'usergroup-3',
            'usergroup_id': 'USERGC',
            'users': {'USERF': 'userf', 'USERG': 'userg'},
            'channels': {'CHANF': 'channelf', 'CHANG': 'channelg'},
            'description': 'Another new usergroup'
        }
    })

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {'slack-workspace': {'slack': slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call('USERGB', ['CHANB', 'CHANC'], 'A new usergroup'),
        call('USERGC', ['CHANF', 'CHANG'], 'Another new usergroup')
    ]
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call('USERGB', ['USERB', 'USERC']),
        call('USERGC', ['USERF', 'USERG'])
    ]
