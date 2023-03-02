import pytest

from reconcile.utils.saasherder import SaasHerder


@pytest.mark.parametrize(
    "allowed_secret_parameter_path,referenced_secret_path,expected_valid",
    [
        # covered by parent directory
        ("foobar", "foobar/baz", True),
        # not covered by parent directory even though there is a common name prefix
        ("foo", "foobar/baz", False),
        # multilevel allowed path
        ("foo/bar", "foo/bar/baz", True),
        # multilevel but different intermediary path
        ("foo/bar", "foo/baz/bar", False),
    ],
)
def test_saasherder_allowed_secret_paths(
    allowed_secret_parameter_path: str,
    referenced_secret_path: str,
    expected_valid: bool,
):
    """
    ensure a parent directory in allowed_secret_parameter_paths matches correctly
    """
    saas_files = [
        {
            "path": "path1",
            "name": "a1",
            "managedResourceTypes": [],
            "allowedSecretParameterPaths": [allowed_secret_parameter_path],
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
                                        "path": referenced_secret_path,
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

    assert saasherder.valid == expected_valid
