import pytest

from reconcile.external_resources.model import (
    ExternalResourceModuleConfiguration,
    ExternalResourceModuleConfigurationError,
    ExternalResourcesSettingsV1,
)
from reconcile.gql_definitions.external_resources.external_resources_modules import (
    ExternalResourcesModuleV1,
)
from reconcile.gql_definitions.external_resources.fragments.external_resources_module_overrides import (
    ExternalResourcesModuleOverrides,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec


@pytest.mark.parametrize(
    ("spec", "overrides", "expected_conf"),
    [
        (  # Module Default
            ExternalResourceSpec(
                provision_provider="aws",
                provisioner={},
                resource={},
                namespace={},
            ),
            None,
            ExternalResourceModuleConfiguration(
                image="stable-image",
                version="1.0.0",
                outputs_secret_image="path/to/er-output-secret-image",
                outputs_secret_version="er-output-secret-version",
                reconcile_timeout_minutes=60,
                reconcile_drift_interval_minutes=60,
                resources={
                    "requests": {"cpu": "100m", "memory": "128Mi"},
                    "limits": {"memory": "4Gi", "cpu": None},
                },
            ),
        ),
        (  # Account channel
            ExternalResourceSpec(
                provision_provider="aws",
                provisioner={"external_resources": {"channel": "candidate"}},
                resource={},
                namespace={},
            ),
            None,
            ExternalResourceModuleConfiguration(
                image="candidate-image",
                version="2.0.0",
                outputs_secret_image="path/to/er-output-secret-image",
                outputs_secret_version="er-output-secret-version",
                reconcile_timeout_minutes=60,
                reconcile_drift_interval_minutes=60,
                resources={
                    "requests": {"cpu": "100m", "memory": "128Mi"},
                    "limits": {"memory": "4Gi", "cpu": None},
                },
            ),
        ),
        (  # Module Overrides image/version
            ExternalResourceSpec(
                provision_provider="aws",
                provisioner={"external_resources": {"channel": "candidate"}},
                resource={"channel": "experiment"},
                namespace={},
            ),
            ExternalResourcesModuleOverrides(
                image="overridden-image",
                version="overridden-version",
                module_type=None,
                channel=None,
                reconcile_timeout_minutes=None,
                outputs_secret_image="overridden-secrets-image",
                outputs_secret_version="overridden-secrets-version",
                resources={
                    "requests": {"cpu": "200m", "memory": "128Mi"},
                    "limits": {"memory": "8Gi", "cpu": None},
                },
            ),
            ExternalResourceModuleConfiguration(
                image="overridden-image",
                version="overridden-version",
                outputs_secret_image="overridden-secrets-image",
                outputs_secret_version="overridden-secrets-version",
                reconcile_timeout_minutes=60,
                reconcile_drift_interval_minutes=60,
                resources={
                    "requests": {"cpu": "200m", "memory": "128Mi"},
                    "limits": {"memory": "8Gi", "cpu": None},
                },
                overridden=True,
            ),
        ),
        (  # Module Overrides channel
            ExternalResourceSpec(
                provision_provider="aws",
                provisioner={"external_resources": {"channel": "candidate"}},
                resource={"channel": "experiment"},
                namespace={},
            ),
            ExternalResourcesModuleOverrides(
                image=None,
                version=None,
                module_type=None,
                channel="experiment-2",
                reconcile_timeout_minutes=None,
                outputs_secret_image="path/to/er-output-secret-image",
                outputs_secret_version="er-output-secret-version",
                resources={
                    "requests": {"cpu": "100m", "memory": "128Mi"},
                    "limits": {"memory": "4Gi", "cpu": None},
                },
            ),
            ExternalResourceModuleConfiguration(
                image="experiment-2-image",
                version="4.0.0",
                outputs_secret_image="path/to/er-output-secret-image",
                outputs_secret_version="er-output-secret-version",
                reconcile_timeout_minutes=60,
                reconcile_drift_interval_minutes=60,
                resources={
                    "requests": {"cpu": "100m", "memory": "128Mi"},
                    "limits": {"memory": "4Gi", "cpu": None},
                },
                overridden=True,
            ),
        ),
    ],
)
def test_module_image_configuration(
    module: ExternalResourcesModuleV1,
    settings: ExternalResourcesSettingsV1,
    spec: ExternalResourceSpec,
    overrides: ExternalResourcesModuleOverrides,
    expected_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec.metadata = {"module_overrides": overrides}

    assert (
        ExternalResourceModuleConfiguration.resolve_configuration(
            module=module, spec=spec, settings=settings
        )
        == expected_conf
    )


def test_module_has_wrong_default_channel(
    module: ExternalResourcesModuleV1,
    settings: ExternalResourcesSettingsV1,
) -> None:
    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "aws-acc-1"},
        resource={"provider": "rds", "identifier": "my-resource"},
        namespace={},
    )

    module.default_channel = "non-existent-channel"
    with pytest.raises(ExternalResourceModuleConfigurationError):
        ExternalResourceModuleConfiguration.resolve_configuration(
            module=module, spec=spec, settings=settings
        )
