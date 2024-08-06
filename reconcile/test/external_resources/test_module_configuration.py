from reconcile.external_resources.model import (
    ExternalResourceModuleConfiguration,
    ExternalResourcesModuleOverridesV1,
    ExternalResourcesModuleV1,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec


def test_module_conf_overrides(module: ExternalResourcesModuleV1) -> None:
    module_overrides = ExternalResourcesModuleOverridesV1(
        image="i_override",
        version="v_override",
        module_type=None,
        reconcile_timeout_minutes=None,
    )
    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={},
        resource={},
        namespace={},
    )
    spec.metadata = {"module_overrides": module_overrides}
    conf = ExternalResourceModuleConfiguration.resolve_configuration(
        module=module, spec=spec
    )
    assert conf.image == module_overrides.image
    assert conf.version == module_overrides.version
    assert (
        conf.reconcile_drift_interval_minutes == module.reconcile_drift_interval_minutes
    )
