import os
from typing import Any, List, Mapping
import pytest

import reconcile.integrations_manager as intop


def test_construct_values_file_empty():
    integrations_specs: List[Mapping[str, Any]] = []
    expected = {
        "excludeService": True,
        "integrations": [],
        "cronjobs": [],
    }
    values = intop.construct_values_file(integrations_specs)
    assert values == expected


def test_construct_values_file():
    integrations_specs: List[Mapping[str, Any]] = [
        {
            "name": "integ1",
        },
        {
            "name": "cron1",
            "cron": "yup",
        },
    ]
    expected = {
        "excludeService": True,
        "integrations": [
            {"name": "integ1"},
        ],
        "cronjobs": [
            {"name": "cron1", "cron": "yup"},
        ],
    }
    values = intop.construct_values_file(integrations_specs)
    assert values == expected


def test_collect_parameters():
    template = {
        "parameters": [
            {
                "name": "tplt_param",
                "value": "default",
            }
        ]
    }
    os.environ["tplt_param"] = "override"
    environment = {
        "parameters": '{"env_param": "test"}',
    }
    parameters = intop.collect_parameters(template, environment)
    expected = {
        "env_param": "test",
        "tplt_param": "override",
    }
    assert parameters == expected


def test_collect_parameters_env_stronger():
    template = {
        "parameters": [
            {
                "name": "env_param",
                "value": "default",
            }
        ]
    }
    environment = {
        "parameters": '{"env_param": "override"}',
    }
    parameters = intop.collect_parameters(template, environment)
    expected = {
        "env_param": "override",
    }
    assert parameters == expected


def test_collect_parameters_os_env_strongest():
    template = {
        "parameters": [
            {
                "name": "env_param",
                "value": "default",
            }
        ]
    }
    os.environ["env_param"] = "strongest"
    environment = {
        "parameters": '{"env_param": "override"}',
    }
    parameters = intop.collect_parameters(template, environment)
    expected = {
        "env_param": "strongest",
    }
    assert parameters == expected


@pytest.fixture
def resources():
    return {
        "requests": {
            "cpu": 1,
            "memory": "1Mi",
        },
        "limits": {
            "cpu": 1,
            "memory": "1Mi",
        },
    }


@pytest.fixture
def integrations(resources):
    return [
        {
            "name": "integ-dont-run",
        },
        {
            "name": "integ1",
            "managed": [
                {
                    "namespace": {
                        "path": "path1",
                        "environment": {
                            "name": "test1",
                        },
                    },
                    "spec": {
                        "resources": resources,
                    },
                },
            ],
        },
        {
            "name": "integ2",
            "managed": [
                {
                    "namespace": {
                        "path": "path2",
                        "environment": {
                            "name": "test2",
                        },
                    },
                    "spec": {
                        "resources": resources,
                    },
                },
            ],
        },
        {
            "name": "integ3",
            "managed": [
                {
                    "namespace": {
                        "path": "path2",
                        "environment": {
                            "name": "test2",
                        },
                    },
                    "spec": {
                        "resources": resources,
                    },
                },
            ],
        },
    ]


def test_collect_namespaces_single_ns(integrations, resources):
    environment_name = "test1"
    namespaces = intop.collect_namespaces(integrations, environment_name)
    expected = [
        {
            "path": "path1",
            "environment": {
                "name": "test1",
            },
            "integration_specs": [
                {
                    "name": "integ1",
                    "resources": resources,
                },
            ],
        },
    ]
    assert namespaces == expected


def test_collect_namespaces_multiple_ns(integrations, resources):
    environment_name = "test2"
    namespaces = intop.collect_namespaces(integrations, environment_name)
    expected = [
        {
            "path": "path2",
            "environment": {
                "name": "test2",
            },
            "integration_specs": [
                {
                    "name": "integ2",
                    "resources": resources,
                },
                {
                    "name": "integ3",
                    "resources": resources,
                },
            ],
        },
    ]
    assert namespaces == expected


def test_collect_namespaces_all_environments(integrations, resources):
    environment_name = ""
    namespaces = intop.collect_namespaces(integrations, environment_name)
    expected = [
        {
            "path": "path1",
            "environment": {
                "name": "test1",
            },
            "integration_specs": [
                {
                    "name": "integ1",
                    "resources": resources,
                },
            ],
        },
        {
            "path": "path2",
            "environment": {
                "name": "test2",
            },
            "integration_specs": [
                {
                    "name": "integ2",
                    "resources": resources,
                },
                {
                    "name": "integ3",
                    "resources": resources,
                },
            ],
        },
    ]
    assert namespaces == expected
