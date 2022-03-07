import pytest

import reconcile.aws_ami_share as integ


@pytest.fixture
def accounts():
    return [
        {
            'name': 'some-account',
            'automationToken': {
                'path': 'path',
            },
            'resourcesDefaultRegion': 'default-region',
            'sharing': [
                {
                    'provider': 'ami',
                    'account': {
                        'name': 'shared-account',
                        'uid': 123,
                    }
                }
            ]
        },
        {
            'name': 'some-account-too',
            'automationToken': {
                'path': 'path',
            },
            'resourcesDefaultRegion': 'default-region',
        },
        {
            'name': 'shared-account',
            'automationToken': {
                'path': 'path',
            },
            'resourcesDefaultRegion': 'default-region',
        }
    ]


def test_filter_accounts(accounts):
    filtered = [a['name'] for a in integ.filter_accounts(accounts)]
    assert filtered == ['some-account', 'shared-account']
