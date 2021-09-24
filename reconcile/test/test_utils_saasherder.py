from unittest.mock import call
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.state import State


def test_publish_promotions(mocker):
    """This tests if the saasherder.publish_promotions method publishes the
    promotions to the State and if it send the command to open the promotion
    MR"""
    commit_sha = '4b12ffb81218788f4ff0856add0f05d37f7217b0'
    stage_deploy_channel = 'service-name-stage-deploy-success-channel'
    post_deploy_test_channel = \
        'service-name-stage-post-deploy-tests-success-channel'

    # The promotion to be deployed in stage
    deploy_promotion = {
        'publish': [
            stage_deploy_channel
        ],
        'commit_sha': commit_sha
    }

    # The promotion that will trigger the autopromotion
    test_promotion = {
        'auto': True,
        'subscribe': [
            stage_deploy_channel
        ],
        'publish': [
            post_deploy_test_channel
        ],
        'commit_sha': commit_sha
    }

    # A minimal deploy saas_file
    deploy_saas_file = {
        'path': '/services/service-name/cicd/deploy.yaml',
        'name': 'saas-service-name',
        'app': {
            'name': 'service-name',
        },
        'managedResourceTypes': [
            'Deployment',
            'Service',
            'PodDisruptionBudget',
        ],
        'resourceTemplates': [{
            'name': 'service-name',
            'url': 'https://github.com/app-sre/service-name',
            'path': '/openshift/service-name.yaml',
            'targets': [
                {
                    'namespace': {},
                    'ref': 'master',
                    'upstream': {},
                    'promotion': deploy_promotion
                },
                {
                    'namespace': {},
                    'ref': commit_sha,
                    'promotion': {
                        'auto': True,
                        'subscribe': [
                            post_deploy_test_channel
                        ]
                    },
                }
            ]
        }]
    }

    # A minimal test saas_file
    test_saas_file = {
        'path': '/services/service-name/cicd/deploy.yaml',
        'name': 'saas-service-name',
        'app': {
            'name': 'service-name',
        },
        'managedResourceTypes': [
            'Deployment',
            'Service',
            'PodDisruptionBudget',
        ],
        'resourceTemplates': [{
            'name': 'service-name',
            'url': 'https://github.com/app-sre/service-name',
            'path': '/openshift/service-name-acceptance.yaml',
            'targets': [
                {
                    'namespace': {},
                    'ref': commit_sha,
                    'upstream': {},
                    'promotion': test_promotion
                },
            ]
        }]
    }

    thread_pool_size = 1
    gitlabapi_mock = mocker.MagicMock(GitLabApi)
    settings = {}

    saas_files = [deploy_saas_file, test_saas_file]
    saasherder = SaasHerder(saas_files, thread_pool_size, gitlabapi_mock,
                            'some_integration', '0.1.0', settings)

    saasherder.promotions = [deploy_promotion]

    state_mock = mocker.MagicMock(State)
    saasherder.state = state_mock

    autopromoter_mock = mocker.patch('reconcile.utils.saasherder.AutoPromoter',
                                     autospec=True)

    # The method beeing tested here
    saasherder.publish_promotions(True, saas_files, gitlabapi_mock)

    # This ensures that State add was called with the correct parameters
    # Which is the actual publish phase
    assert state_mock.add.call_count == 1
    assert state_mock.add.call_args == [
        (f'promotions/{stage_deploy_channel}/{commit_sha}', {'success': True}),
        {'force': True}
    ]

    # This ensures that the promotion MR creation was tried
    assert autopromoter_mock.call_count == 1
    assert autopromoter_mock.call_args == [(saasherder.promotions,), {}]

    assert autopromoter_mock.mock_calls[1] == call().submit(cli=gitlabapi_mock)
