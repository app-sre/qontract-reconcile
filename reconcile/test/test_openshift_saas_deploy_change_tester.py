from collections.abc import Callable

import pytest

from reconcile.openshift_saas_deploy_change_tester import (
    State,
    collect_compare_diffs,
    collect_state,
)
from reconcile.typed_queries.saas_files import SaasFile


@pytest.fixture
def saas_files(gql_class_factory: Callable[..., SaasFile]) -> list[SaasFile]:
    return [
        gql_class_factory(
            SaasFile,
            {
                "path": "/path.yml",
                "name": "saas-file-name",
                "app": {"name": "ccx-data-pipeline"},
                "pipelinesProvider": {
                    "name": "pipeline-provider-01",
                    "provider": "tekton",
                    "namespace": {
                        "name": "namespace",
                        "cluster": {
                            "name": "appint-ex-01",
                            "serverUrl": "https://cluster-url",
                            "internal": False,
                            "automationToken": {"path": "creds", "field": "token"},
                            "consoleUrl": "https://console-url",
                        },
                    },
                    "defaults": {
                        "pipelineTemplates": {
                            "openshiftSaasDeploy": {"name": "saas-deploy"}
                        }
                    },
                },
                "deployResources": {
                    "requests": {"cpu": "1500m", "memory": "700Mi"},
                    "limits": {"cpu": "2000m", "memory": "1Gi"},
                },
                "managedResourceTypes": [
                    "Deployment",
                ],
                "takeover": None,
                "deprecated": None,
                "compare": None,
                "clusterAdmin": None,
                "imagePatterns": [
                    "quay.io/some-org",
                ],
                "allowedSecretParameterPaths": None,
                "use_channel_in_image_tag": None,
                "parameters": '{"SAAS_DEFAULT_1":"saas", "SAAS_DEFAULT_2":"saas"}',
                "secretParameters": [
                    {
                        "name": "saas_default_1",
                        "secret": {
                            "field": "saas_field_1",
                            "path": "saas_path_1",
                            "version": 1,
                        },
                    },
                    {
                        "name": "saas_default_2",
                        "secret": {
                            "field": "saas_field_2",
                            "path": "saas_path_2",
                            "version": 1,
                        },
                    },
                ],
                "resourceTemplates": [
                    {
                        "name": "tmpl",
                        "url": "https://github.com/some-org/some-repo.git",
                        "path": "/deploy.yaml",
                        "hash_length": 7,
                        "parameters": '{"TMPL_DEFAULT_1":"tmpl", "TMPL_DEFAULT_2":"tmpl"}',  # used in collect_state but not saasherder
                        "secretParameters": [  # used in collect_state but saasherder
                            {
                                "name": "tmpl_default_1",
                                "secret": {
                                    "field": "tmpl_field_1",
                                    "path": "tmpl_path_1",
                                    "version": 1,
                                },
                            },
                            {
                                "name": "tmpl_default_2",
                                "secret": {
                                    "field": "tmpl_field_2",
                                    "path": "tmpl_path_2",
                                    "version": 1,
                                },
                            },
                        ],
                        "targets": [
                            {
                                "name": "target",
                                "namespace": {
                                    "name": "namespace",
                                    "environment": {
                                        "name": "env-name",
                                        # used in collect_state but not saas_file_owners
                                        "parameters": '{ "ENV_DEFAULT_1": "env", "ENV_DEFAULT_2": "env" }',
                                        "secretParameters": [
                                            {
                                                "name": "env_default_1",
                                                "secret": {
                                                    "field": "env_field_1",
                                                    "path": "env_path_1",
                                                    "version": 1,
                                                },
                                            },
                                            {
                                                "name": "env_default_2",
                                                "secret": {
                                                    "field": "env_field_2",
                                                    "path": "env_path_2",
                                                    "version": 1,
                                                },
                                            },
                                        ],
                                    },
                                    "app": {"name": "app"},
                                    "cluster": {"name": "cluster"},
                                },
                                "ref": "master",
                                "promotion": None,
                                "parameters": '{"TARGET":"target", "ENV_DEFAULT_1":"target", "SAAS_DEFAULT_1":"target", "TMPL_DEFAULT_1":"target"}',
                                "secretParameters": [
                                    {
                                        "name": "target_default",
                                        "secret": {
                                            "field": "target_field",
                                            "path": "target_path",
                                            "version": 1,
                                            "format": None,
                                        },
                                    },
                                    {
                                        "name": "saas_default_1",
                                        "secret": {
                                            "field": "target_field",
                                            "path": "target_path",
                                            "version": 1,
                                            "format": None,
                                        },
                                    },
                                    {
                                        "name": "tmpl_default_1",
                                        "secret": {
                                            "field": "target_field",
                                            "path": "target_path",
                                            "version": 1,
                                            "format": None,
                                        },
                                    },
                                    {
                                        "name": "env_default_1",
                                        "secret": {
                                            "field": "target_field",
                                            "path": "target_path",
                                            "version": 1,
                                            "format": None,
                                        },
                                    },
                                ],
                                "upstream": {
                                    "instance": {
                                        "name": "ci",
                                        "serverUrl": "https://ci.example.net",
                                    },
                                    "name": "job-name",
                                },
                                "image": None,
                                "disable": None,
                                "delete": None,
                            },
                        ],
                    }
                ],
            },
        )
    ]


def test_collect_state(saas_files: list[SaasFile]) -> None:
    """
    this implementation of collect_state may contain a bug when compared to the
    saas_herder way to of collecting parameters and secrets.
    there are 4 places where parameters and secrets can be defined with qontract-schema:
    1) environment-1
    2) saas-file-2
    3) saas-file-2.resourceTemplates
    4) saas-file-2.resourceTemplates.targets

    - saas-herder collects from 1), 2), 4)
    - collect_state collects from 2), 3), 4)
    """
    state = collect_state(saas_files)
    expected = State(
        **{
            "saas_file_path": "/path.yml",
            "saas_file_name": "saas-file-name",
            "saas_file_deploy_resources": {
                "requests": {"cpu": "1500m", "memory": "700Mi"},
                "limits": {"cpu": "2000m", "memory": "1Gi"},
            },
            "resource_template_name": "tmpl",
            "namespace": "namespace",
            "environment": "env-name",
            "cluster": "cluster",
            "url": "https://github.com/some-org/some-repo.git",
            "ref": "master",
            "parameters": {
                "SAAS_DEFAULT_1": "target",
                "SAAS_DEFAULT_2": "saas",
                "ENV_DEFAULT_1": "target",
                # "ENV_DEFAULT_2": "env", # todo - check if it is a bug or on purpose that environment-1 params are not loaded
                "TMPL_DEFAULT_1": "target",
                "TMPL_DEFAULT_2": "tmpl",
                "TARGET": "target",
            },
            "secret_parameters": {
                "target_default": {
                    "field": "target_field",
                    "path": "target_path",
                    "version": 1,
                    "format": None,
                },
                "saas_default_1": {
                    "field": "target_field",
                    "path": "target_path",
                    "version": 1,
                    "format": None,
                },
                "saas_default_2": {
                    "field": "saas_field_2",
                    "path": "saas_path_2",
                    "version": 1,
                    "format": None,
                },
                "env_default_1": {
                    "field": "target_field",
                    "path": "target_path",
                    "version": 1,
                    "format": None,
                },
                # environment-1 secrets should be present since saasherder uses them but collect_state does sadly not
                # "env_default_2": {
                #    "field": "env_field_2",
                #    "path": "env_path_2",
                #    "version": 1,
                #    "format": None,
                # },
                "tmpl_default_1": {
                    "field": "target_field",
                    "path": "target_path",
                    "version": 1,
                    "format": None,
                },
                "tmpl_default_2": {
                    "field": "tmpl_field_2",
                    "path": "tmpl_path_2",
                    "version": 1,
                    "format": None,
                },
            },
            "upstream": {
                "instance": {"name": "ci", "serverUrl": "https://ci.example.net"},
                "name": "job-name",
            },
            "saas_file_definitions": {
                "managed_resource_types": ["Deployment"],
                "image_patterns": ["quay.io/some-org"],
                "use_channel_in_image_tag": False,
            },
            "disable": None,
            "delete": None,
            "target_path": None,
        }
    )
    assert state == [expected]


def test_collect_compare_diffs(saas_files: list[SaasFile]):
    state_1 = collect_state(saas_files)
    state_2 = [s.copy() for s in state_1]
    state_1[0].ref = "another-branch"
    diffs = collect_compare_diffs(
        state_1, state_2, changed_paths=[state_1[0].saas_file_path]
    )
    assert diffs == {
        "https://github.com/some-org/some-repo.git/compare/another-branch...master"
    }


def test_collect_compare_diffs_other_paths(saas_files: list[SaasFile]):
    state_1 = collect_state(saas_files)
    state_2 = [s.copy() for s in state_1]
    state_1[0].ref = "another-branch"
    diffs = collect_compare_diffs(
        state_1, state_2, changed_paths=["/some/other-path.yml"]
    )
    assert diffs == set()
