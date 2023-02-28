from reconcile.utils.saasherder import SaasHerder


def test_saasherder_allowed_secret_paths_parent_directory():
    """
    ensure a parent directory in allowed_secret_parameter_paths matches correctly
    """
    saas_files = [
        {
            "path": "path1",
            "name": "a1",
            "managedResourceTypes": [],
            "allowedSecretParameterPaths": [
                "foobar",
            ],
            "resourceTemplates": [
                {
                    "name": "test",
                    "url": "url",
                    "targets": [
                        {
                            "namespace": {
                                "name": "ns",
                                "environment": {"name": "env1", "parameters": "{}"},
                                "cluster": {"name": "cluster"},
                            },
                            "ref": "main",
                            "upstream": {"instance": {"name": "ci"}, "name": "job"},
                            "parameters": {},
                            "secretParameters": [
                                {
                                    "name": "secret",
                                    "secret": {
                                        "path": "foobar/baz",
                                        "field": "db.endpoint",
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
            "selfServiceRoles": [
                {"users": [{"org_username": "theirname"}], "bots": []}
            ],
        },
    ]

    saasherder = SaasHerder(
        saas_files,
        thread_pool_size=1,
        gitlab=None,
        integration="",
        integration_version="",
        settings={},
        validate=True,
    )

    assert saasherder.valid


def test_saasherder_allowed_secret_paths_invalid_parent_directory():
    """
    ensure a prefix directory allowed_secret_parameter_paths is not incorrectly identified as a parent
    """
    saas_files = [
        {
            "path": "path1",
            "name": "a1",
            "managedResourceTypes": [],
            "allowedSecretParameterPaths": [
                "foo",
            ],
            "resourceTemplates": [
                {
                    "name": "test",
                    "url": "url",
                    "targets": [
                        {
                            "namespace": {
                                "name": "ns",
                                "environment": {"name": "env1", "parameters": "{}"},
                                "cluster": {"name": "cluster"},
                            },
                            "ref": "main",
                            "upstream": {"instance": {"name": "ci"}, "name": "job"},
                            "parameters": {},
                            "secretParameters": [
                                {
                                    "name": "secret",
                                    "secret": {
                                        "path": "foobar/baz",
                                        "field": "db.endpoint",
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
            "selfServiceRoles": [
                {"users": [{"org_username": "theirname"}], "bots": []}
            ],
        },
    ]

    saasherder = SaasHerder(
        saas_files,
        thread_pool_size=1,
        gitlab=None,
        integration="",
        integration_version="",
        settings={},
        validate=True,
    )

    assert not saasherder.valid
