from reconcile.external_resources.model import (
    ExternalResourceModuleConfiguration,
    ExternalResourcesModuleOverridesV1,
    ExternalResourcesModuleV1,
    ExternalResourcesSettingsV1,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec


def test_module_conf_overrides(
    module: ExternalResourcesModuleV1, settings: ExternalResourcesSettingsV1
) -> None:
    module_overrides = ExternalResourcesModuleOverridesV1(
        image="i_override",
        version="v_override",
        module_type=None,
        reconcile_timeout_minutes=None,
        outputs_secret_image="whatever-image",
        outputs_secret_version="whatever-version",
    )
    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={},
        resource={},
        namespace={},
    )
    spec.metadata = {"module_overrides": module_overrides}
    conf = ExternalResourceModuleConfiguration.resolve_configuration(
        module=module, spec=spec, settings=settings
    )
    assert conf.image == module_overrides.image
    assert conf.version == module_overrides.version
    assert (
        conf.reconcile_drift_interval_minutes == module.reconcile_drift_interval_minutes
    )
    assert conf.outputs_secret_image == module_overrides.outputs_secret_image
    assert conf.outputs_secret_version == module_overrides.outputs_secret_version
