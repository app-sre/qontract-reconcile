"""
Unit tests for imagePatternsBlockRules feature in SaasHerder._check_images
"""

from typing import Any
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.saasherder.models import (
    ImageAuth,
    ImagePatternsBlockRule,
    TargetSpec,
)
from reconcile.utils.saasherder.saasherder import SaasHerder


@pytest.fixture
def mock_secret_reader() -> MagicMock:
    """Mock secret reader"""
    return MagicMock()


@pytest.fixture
def mock_github() -> MagicMock:
    """Mock GitHub client"""
    return MagicMock()


@pytest.fixture
def saas_file(gql_class_factory: Any, request: Any) -> SaasFile:
    """Create a saas file with specified environment labels"""

    # Handle parametrized and non-parametrized tests
    if hasattr(request, "param") and request.param:
        env_name = request.param.get("env_name", "production")
        env_labels = request.param.get("env_labels", '{"type": "production"}')
    else:
        env_name = "production"
        env_labels = '{"type": "production"}'

    saas_file_data = {
        "name": "test-saas-file",
        "app": {"name": "test-app"},
        "pipelinesProvider": {"name": "test-provider"},
        "managedResourceTypes": [],
        "imagePatterns": ["quay.io/allowed"],
        "resourceTemplates": [
            {
                "name": "test-template",
                "url": "https://github.com/test/repo",
                "path": "/templates/deploy.yaml",
                "targets": [
                    {
                        "namespace": {
                            "name": "test-namespace",
                            "environment": {
                                "name": env_name,
                                "labels": env_labels,
                            },
                            "app": {"name": "test-app"},
                            "cluster": {"name": "test-cluster"},
                        },
                        "ref": "main",
                    }
                ],
            }
        ],
    }
    return gql_class_factory(SaasFile, saas_file_data)


@pytest.fixture
def target_spec(
    saas_file: SaasFile, mock_secret_reader: MagicMock, mock_github: MagicMock
) -> TargetSpec:
    """Create a TargetSpec from saas_file"""
    resource_template = saas_file.resource_templates[0]
    target = resource_template.targets[0]
    return TargetSpec(
        saas_file=saas_file,
        resource_template=resource_template,
        target=target,
        image_auth=ImageAuth(),
        hash_length=7,
        github=mock_github,
        target_config_hash="abc1234",
        secret_reader=mock_secret_reader,
    )


@pytest.fixture
def resources_with_blocked_image() -> list[dict[str, Any]]:
    """Create resources with blocked image pattern"""
    return [
        {
            "kind": "Deployment",
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"image": "quay.io/blocked/test-image:latest"}]
                    }
                }
            },
        }
    ]


@pytest.fixture
def resources_with_allowed_image() -> list[dict[str, Any]]:
    """Create resources with allowed image"""
    return [
        {
            "kind": "Deployment",
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"image": "quay.io/allowed/test-image:latest"}]
                    }
                }
            },
        }
    ]


@pytest.fixture
def resources_with_no_images() -> list[dict[str, Any]]:
    """Create resources with no images"""
    return [{"kind": "ConfigMap", "data": {"key": "value"}}]


@pytest.fixture
def image_patterns_block_config() -> dict[str, Any]:
    """Configuration for imagePatternsBlockRules"""
    return {
        "imagePatternsBlockRules": [
            {
                "environmentLabelSelector": {"type": "production"},
                "imagePatterns": ["quay.io/blocked"],
            }
        ]
    }


@pytest.fixture
def image_patterns_block_config_multiple_patterns() -> dict[str, Any]:
    """Configuration with multiple blocked patterns"""
    return {
        "imagePatternsBlockRules": [
            {
                "environmentLabelSelector": {"type": "production"},
                "imagePatterns": ["quay.io/blocked", "registry.io/forbidden"],
            }
        ]
    }


@pytest.fixture
def image_patterns_block_rules() -> list[ImagePatternsBlockRule]:
    """Image pattern block rules for direct testing"""
    return [
        ImagePatternsBlockRule(
            environment_label_selector={"type": "production"},
            image_patterns=["quay.io/blocked"],
        )
    ]


@pytest.fixture
def image_patterns_block_rules_multiple_patterns() -> list[ImagePatternsBlockRule]:
    """Image pattern block rules with multiple patterns"""
    return [
        ImagePatternsBlockRule(
            environment_label_selector={"type": "production"},
            image_patterns=["quay.io/blocked", "registry.io/forbidden"],
        )
    ]


@pytest.fixture
def saasherder(
    saas_file: SaasFile,
    mock_secret_reader: MagicMock,
    image_patterns_block_rules: list[ImagePatternsBlockRule],
) -> SaasHerder:
    """Create a SaasHerder instance with ImagePatternsBlockRule objects"""
    return SaasHerder(
        [saas_file],
        secret_reader=mock_secret_reader,
        thread_pool_size=1,
        integration="",
        integration_version="",
        hash_length=7,
        repo_url="https://repo-url.com",
        image_patterns_block_rules=image_patterns_block_rules,
    )


@pytest.mark.parametrize(
    "saas_file,expected_error,mock_image_return",
    [
        (
            {"env_name": "production", "env_labels": '{"type": "production"}'},
            True,
            None,
        ),
        (
            {"env_name": "stage", "env_labels": '{"type": "stage"}'},
            False,
            MagicMock(),
        ),
    ],
    indirect=["saas_file"],
)
def test_blocked_image_by_environment(
    target_spec: TargetSpec,
    resources_with_blocked_image: list[dict[str, Any]],
    saasherder: SaasHerder,
    expected_error: bool,
    mock_image_return: Any,
) -> None:
    """Test that blocked images are caught in matching environments"""
    with patch.object(saasherder, "_get_image", return_value=mock_image_return):
        result = saasherder._check_images(
            spec=target_spec,
            resources=resources_with_blocked_image,
        )

    assert result is expected_error


def test_allowed_image_no_error(
    target_spec: TargetSpec,
    resources_with_allowed_image: list[dict[str, Any]],
    saasherder: SaasHerder,
) -> None:
    """Test that allowed images pass validation"""
    mock_image = MagicMock()
    with patch.object(saasherder, "_get_image", return_value=mock_image):
        result = saasherder._check_images(
            spec=target_spec,
            resources=resources_with_allowed_image,
        )

    assert result is False  # No error


@pytest.mark.parametrize(
    "saas_file",
    [{"env_name": "production", "env_labels": '{"type": "production"}'}],
    indirect=True,
)
def test_no_images_no_error(
    target_spec: TargetSpec,
    resources_with_no_images: list[dict[str, Any]],
    saasherder: SaasHerder,
) -> None:
    """Test that targets with no images pass validation"""
    result = saasherder._check_images(
        spec=target_spec,
        resources=resources_with_no_images,
    )

    assert result is False  # No error


@pytest.mark.parametrize(
    "saas_file",
    [{"env_name": "production", "env_labels": '{"type": "production"}'}],
    indirect=True,
)
def test_no_config_backward_compatible(
    target_spec: TargetSpec,
    resources_with_blocked_image: list[dict[str, Any]],
    saas_file: SaasFile,
    mock_secret_reader: MagicMock,
) -> None:
    """Test that no imagePatternsBlockRules config is backward compatible"""
    saasherder_no_rules = SaasHerder(
        [saas_file],
        secret_reader=mock_secret_reader,
        thread_pool_size=1,
        integration="",
        integration_version="",
        hash_length=7,
        repo_url="https://repo-url.com",
        image_patterns_block_rules=None,  # No rules
    )

    with patch.object(saasherder_no_rules, "_get_image", return_value=None):
        result = saasherder_no_rules._check_images(
            spec=target_spec,
            resources=resources_with_blocked_image,
        )

    # Should proceed to normal imagePatterns validation
    assert result is True  # Error from imagePatterns validation


@pytest.mark.parametrize(
    "saas_file",
    [{"env_name": "production", "env_labels": '{"type": "production"}'}],
    indirect=True,
)
def test_multiple_blocked_images(
    target_spec: TargetSpec,
    image_patterns_block_config: dict[str, Any],
    saas_file: SaasFile,
    mock_secret_reader: MagicMock,
) -> None:
    """Test that multiple blocked images in same resource are all caught"""
    resources = [
        {
            "kind": "Deployment",
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"image": "quay.io/blocked/image1:latest"},
                            {"image": "quay.io/blocked/image2:latest"},
                        ]
                    }
                }
            },
        }
    ]

    block_rules_raw = image_patterns_block_config.get("imagePatternsBlockRules", [])
    block_rules = [
        ImagePatternsBlockRule(
            environment_label_selector=rule["environmentLabelSelector"],
            image_patterns=rule["imagePatterns"],
        )
        for rule in block_rules_raw
    ]
    saasherder = SaasHerder(
        [saas_file],
        secret_reader=mock_secret_reader,
        thread_pool_size=1,
        integration="",
        integration_version="",
        hash_length=7,
        repo_url="https://repo-url.com",
        image_patterns_block_rules=block_rules,
    )

    with patch.object(saasherder, "_get_image", return_value=None):
        result = saasherder._check_images(
            spec=target_spec,
            resources=resources,
        )

    assert result is True  # Error found


@pytest.mark.parametrize(
    "saas_file",
    [{"env_name": "production", "env_labels": '{"type": "production"}'}],
    indirect=True,
)
def test_multiple_blocked_patterns(
    target_spec: TargetSpec,
    image_patterns_block_config_multiple_patterns: dict[str, Any],
    saas_file: SaasFile,
    mock_secret_reader: MagicMock,
) -> None:
    """Test that multiple blocked patterns in same rule are checked"""
    resources = [
        {
            "kind": "Deployment",
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"image": "registry.io/forbidden/test:latest"}]
                    }
                }
            },
        }
    ]

    block_rules_raw = image_patterns_block_config_multiple_patterns.get(
        "imagePatternsBlockRules", []
    )
    block_rules = [
        ImagePatternsBlockRule(
            environment_label_selector=rule["environmentLabelSelector"],
            image_patterns=rule["imagePatterns"],
        )
        for rule in block_rules_raw
    ]
    saasherder = SaasHerder(
        [saas_file],
        secret_reader=mock_secret_reader,
        thread_pool_size=1,
        integration="",
        integration_version="",
        hash_length=7,
        repo_url="https://repo-url.com",
        image_patterns_block_rules=block_rules,
    )

    with patch.object(saasherder, "_get_image", return_value=None):
        result = saasherder._check_images(
            spec=target_spec,
            resources=resources,
        )

    assert result is True  # Error found
